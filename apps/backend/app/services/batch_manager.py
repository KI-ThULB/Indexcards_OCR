import json
import os
import re
import shutil
import time
import uuid
import fcntl
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from app.core.config import settings
from app.core.images import iter_image_files
from app.core.security import validate_batch_name, validate_session_id


class BatchMissingError(RuntimeError):
    """The batch directory a caller wants to operate on does not exist.

    Distinguished from "already locked" on purpose. ``acquire_batch_lock`` used
    to let the underlying ``FileNotFoundError`` escape, which the bulk
    orchestrator turned into a run failed with a raw
    ``[Errno 2] … /.run.lock`` message — and a caller checking only for a False
    return would have read a vanished batch as a lock conflict.
    """


class BatchManager:
    def __init__(self, data_dir: str = settings.DATA_DIR):
        self.data_dir = Path(data_dir)
        self.temp_dir = Path(settings.TEMP_DIR)
        self.batches_dir = Path(settings.BATCHES_DIR)
        
        # Ensure directories exist
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.batches_dir.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _batch_operations_lock(self):
        """Coordinate OCR starts and deletions across local worker processes."""
        lock_path = self.batches_dir / ".batch-operations.lock"

        with open(lock_path, "a+b") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def generate_session_id(self) -> str:
        return str(uuid.uuid4())

    def get_temp_session_path(self, session_id: str) -> Path:
        validate_session_id(session_id)  # reject traversal before touching the FS (W-02)
        session_path = self.temp_dir / session_id
        session_path.mkdir(parents=True, exist_ok=True)
        return session_path

    def create_batch(
        self,
        custom_name: str,
        session_id: str,
        fields: Optional[List[str]] = None,
        prompt_template: Optional[str] = None,
        field_rules: Optional[Dict[str, Any]] = None,
        corrector_enabled: bool = False,
        corrector_cap: Optional[int] = 100,
        authority_bindings: Optional[Dict[str, Any]] = None,  # Phase 11 — same pattern as field_rules
        describe_pictures: bool = False,
        field_groups: Optional[Dict[str, Any]] = None,        # repeatable groups, same pattern
    ) -> str:
        """
        Moves files from temp session to a new permanent batch directory.
        Returns the generated batch name.
        Naming convention: [Custom Name]_[Human Readable Timestamp]_[Unique ID]
        """
        temp_path = self.get_temp_session_path(session_id)
        if not temp_path.exists() or not any(temp_path.iterdir()):
            raise ValueError(f"No files found for session {session_id}")

        # Sanitize custom_name: replace characters illegal on Windows (< > : " / \ | ? *)
        safe_name = re.sub(r'[<>:"/\\|?*]', '-', custom_name)
        unique_id = str(uuid.uuid4())[:8]
        batch_name = f"{safe_name}_{unique_id}"
        batch_path = self.batches_dir / batch_name
        
        # Create batch directory
        batch_path.mkdir(parents=True, exist_ok=False)

        # Store fields in config.json
        config_data = {
            "custom_name": custom_name,
            "fields": fields or settings.FIELD_KEYS,
            "prompt_template": prompt_template,
            "field_rules": field_rules,
            "authority_bindings": authority_bindings,   # Phase 11: same pattern as field_rules
            "field_groups": field_groups,               # repeatable groups (None = scalar only)
            "corrector_enabled": corrector_enabled,
            "corrector_cap": corrector_cap,
            "describe_pictures": describe_pictures,
            "created_at": datetime.now().isoformat()
        }
        with open(batch_path / "config.json", "w") as f:
            json.dump(config_data, f, indent=2)

        # Move files
        for item in temp_path.iterdir():
            if item.is_file():
                shutil.move(str(item), str(batch_path / item.name))

        # Cleanup temp session directory
        shutil.rmtree(str(temp_path))

        # Record History
        self._record_history(batch_name, custom_name, fields)

        return batch_name

    def _record_history(self, batch_name: str, custom_name: str, fields: Optional[List[str]] = None):
        history_file = Path(settings.BATCHES_HISTORY_FILE)
        history = []
        if history_file.exists():
            try:
                with open(history_file, "r") as f:
                    history = json.load(f)
            except Exception:
                history = []
        
        history.append({
            "batch_name": batch_name,
            "custom_name": custom_name,
            "created_at": datetime.now().isoformat(),
            "status": "uploaded",
            "progress": 0,
            "fields": fields or settings.FIELD_KEYS
        })
        
        with open(history_file, "w") as f:
            json.dump(history, f, indent=2)

    def update_batch_status(self, batch_name: str, status: str) -> None:
        """Update the status field of a batch in batches.json.
        Stamps completed_at when the batch first reaches 'completed' (used by retention)."""
        history_file = Path(settings.BATCHES_HISTORY_FILE)
        if not history_file.exists():
            return
        try:
            with open(history_file, "r") as f:
                history = json.load(f)
            for entry in history:
                if entry.get("batch_name") == batch_name:
                    entry["status"] = status
                    if status == "completed" and not entry.get("completed_at"):
                        entry["completed_at"] = datetime.now().isoformat()
                    break
            with open(history_file, "w") as f:
                json.dump(history, f, indent=2)
        except Exception:
            pass  # non-critical — status display is cosmetic

    def get_history(self) -> list:
        """Read batches.json and return enriched batch history entries."""
        history_file = Path(settings.BATCHES_HISTORY_FILE)
        if not history_file.exists():
            return []

        try:
            with open(history_file, "r") as f:
                history = json.load(f)
        except Exception:
            return []

        enriched = []
        for entry in history:
            batch_name = entry.get("batch_name", "")
            batch_path = self.batches_dir / batch_name

            # files_count: count image files live if directory exists, else use stored value
            if batch_path.exists():
                files_count = len(iter_image_files(batch_path))
            else:
                files_count = entry.get("files_count", 0)

            # has_errors / error_count
            error_dir = batch_path / "_errors"
            if error_dir.exists():
                error_files = [f for f in error_dir.iterdir() if f.is_file()]
                has_errors = len(error_files) > 0
                error_count = len(error_files)
            else:
                has_errors = False
                error_count = 0

            enriched.append({
                "batch_name": batch_name,
                "custom_name": entry.get("custom_name", batch_name),
                "created_at": entry.get("created_at", ""),
                "status": entry.get("status", "uploaded"),
                "files_count": files_count,
                "fields": entry.get("fields", []),
                "has_errors": has_errors,
                "error_count": error_count,
            })

        return enriched

    def delete_batch(self, batch_name: str) -> bool:
        """Delete an inactive batch and remove its history entry.

        Raises RuntimeError if an OCR run is active.
        Returns False if the batch does not exist.
        """
        validate_batch_name(batch_name)

        with self._batch_operations_lock():
            batch_path = self.batches_dir / batch_name
            history_file = Path(settings.BATCHES_HISTORY_FILE)

            # Never delete a batch while OCR is running.
            if self.is_run_active(batch_name):
                raise RuntimeError(
                    f"Batch '{batch_name}' cannot be deleted while OCR is running"
                )

            history = []
            if history_file.exists():
                try:
                    with open(history_file, "r") as f:
                        history = json.load(f)
                except Exception:
                    history = []

            original_length = len(history)
            history = [
                e for e in history
                if e.get("batch_name") != batch_name
            ]

            found_in_history = len(history) < original_length
            found_on_disk = batch_path.exists()

            if not found_in_history and not found_on_disk:
                return False

            if found_on_disk:
                shutil.rmtree(str(batch_path))

            with open(history_file, "w") as f:
                json.dump(history, f, indent=2)

            return True

    def _read_history_raw(self) -> list:
        """Read batches.json as-is (no enrichment). Returns [] on absence/corruption."""
        history_file = Path(settings.BATCHES_HISTORY_FILE)
        if not history_file.exists():
            return []
        try:
            with open(history_file, "r") as f:
                return json.load(f)
        except Exception:
            return []

    def _write_history_raw(self, history: list) -> None:
        history_file = Path(settings.BATCHES_HISTORY_FILE)
        with open(history_file, "w") as f:
            json.dump(history, f, indent=2)

    def is_run_active(self, batch_name: str) -> bool:
        """True while an OCR run holds the batch lock (never purge such a batch)."""
        return self._lock_path(batch_name).exists()

    def set_exporting(self, batch_name: str, exporting: bool) -> None:
        """Mark/unmark a batch as mid-export so retention never purges under it."""
        marker = self.get_batch_path(batch_name) / ".exporting"
        if exporting:
            marker.touch()
        else:
            try:
                marker.unlink(missing_ok=True)
            except OSError:
                pass

    def is_exporting(self, batch_name: str) -> bool:
        try:
            return (self.batches_dir / batch_name / ".exporting").exists()
        except OSError:
            return False

    def purge_batch_data(self, batch_name: str) -> bool:
        """Purge inactive batch data while retaining a history tombstone."""
        validate_batch_name(batch_name)

        with self._batch_operations_lock():
            if self.is_run_active(batch_name):
                raise RuntimeError(
                    f"Refusing to purge '{batch_name}': a run is active"
                )

            batch_path = self.batches_dir / batch_name
            existed = batch_path.exists()

            if existed:
                shutil.rmtree(str(batch_path))

            # Retain minimal history information for accountability.
            history = self._read_history_raw()
            changed = False

            for entry in history:
                if entry.get("batch_name") == batch_name:
                    entry["status"] = "purged"
                    entry["purged_at"] = datetime.now().isoformat()
                    entry.pop("files_count", None)
                    changed = True
                    break

            if changed:
                self._write_history_raw(history)

            return existed

    def cleanup_stale_sessions(self, max_age_hours: int = 24) -> int:
        """Remove temp session directories older than max_age_hours.
        Returns the count of cleaned-up sessions."""
        if not self.temp_dir.exists():
            return 0
        now = time.time()
        max_age_seconds = max_age_hours * 3600
        cleaned = 0
        for entry in self.temp_dir.iterdir():
            if entry.is_dir():
                try:
                    age = now - entry.stat().st_mtime
                    if age > max_age_seconds:
                        shutil.rmtree(str(entry))
                        cleaned += 1
                except OSError:
                    pass
        return cleaned

    def delete_session(self, session_id: str) -> bool:
        """Delete a temp upload session directory.
        Returns True if found and deleted, False if not found."""
        validate_session_id(session_id)  # reject traversal before shutil.rmtree (W-02)
        session_path = self.temp_dir / session_id
        if session_path.exists():
            shutil.rmtree(str(session_path))
            return True
        return False

    def list_batches(self) -> List[str]:
        if not self.batches_dir.exists():
            return []
        return [d.name for d in self.batches_dir.iterdir() if d.is_dir()]

    def get_batch_path(self, batch_name: str) -> Path:
        validate_batch_name(batch_name)  # anchor every batch path operation (W-05/K-3)
        return self.batches_dir / batch_name

    # ------------------------------------------------------------------
    # Single-active-run-per-batch lock (W-06/H-2/M-6)
    #
    # An atomic O_EXCL lockfile in the batch directory ensures only one OCR
    # run processes a batch at a time — prevents concurrent runs racing on
    # checkpoint.json and multiplying OpenRouter/Ollama cost. The exclusive
    # create is atomic on a local FS, so it is also correct across uvicorn
    # workers on one host.
    # ------------------------------------------------------------------
    def _lock_path(self, batch_name: str) -> Path:
        return self.get_batch_path(batch_name) / ".run.lock"

    def acquire_batch_lock(self, batch_name: str) -> bool:
        """Atomically acquire the OCR run lock, coordinated with deletion."""
        validate_batch_name(batch_name)

        with self._batch_operations_lock():
            lock = self._lock_path(batch_name)

            try:
                fd = os.open(
                    str(lock),
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
            except FileExistsError:
                return False
            except FileNotFoundError as e:
                raise BatchMissingError(
                    f"Batch '{batch_name}' no longer exists; please re-import it."
                ) from e

            try:
                os.write(fd, str(os.getpid()).encode())
            finally:
                os.close(fd)

            return True

    def release_batch_lock(self, batch_name: str) -> None:
        """Remove the run lockfile if present (safe to call unconditionally)."""
        try:
            self._lock_path(batch_name).unlink(missing_ok=True)
        except OSError:
            pass

batch_manager = BatchManager()
