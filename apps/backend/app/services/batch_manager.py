import json
import asyncio
import hashlib
import os
import re
import shutil
import time
import uuid
import fcntl
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TypeVar
from app.core.transactions import Resource, TransactionCoordinator, TransactionError
from app.core.registry import RegistryError, read_registry, write_registry
from app.core.atomic_io import atomic_write_json
from app.core.checkpoint import read_checkpoint
from app.core.config import settings
from app.core.images import iter_image_files
from app.core.security import validate_batch_name, validate_session_id, validate_filename
from app.services.ws_manager import ws_manager

T = TypeVar("T")


class _BatchFailure(TransactionError):
    """Transport domain errors through SAR-04a without exposing their text."""
    code = "batch_transaction_failed"

    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error


def _protected(operation: Callable[[], T]) -> Callable[[], T]:
    def invoke() -> T:
        try:
            return operation()
        except Exception as exc:
            raise _BatchFailure(exc) from None
    return invoke


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

    @staticmethod
    def _canonical_path(path: Path) -> Path:
        """Use actual directory entries, including on case-insensitive POSIX.

        Names, not inodes, retain the lock identity across deletion/recreation.
        External rename/delete races remain outside the cooperating writer model.
        """
        resolved = path.resolve()
        if resolved == resolved.parent:
            return resolved
        parent = BatchManager._canonical_path(resolved.parent)
        candidate = parent / resolved.name
        try:
            for entry in parent.iterdir():
                if entry.is_symlink():
                    continue
                try:
                    if entry.samefile(candidate):
                        return entry
                except FileNotFoundError:
                    continue
        except FileNotFoundError:
            # A not-yet-created name has no aliases to resolve.
            pass
        return candidate

    @staticmethod
    def _transactions(batch_path: Path) -> TransactionCoordinator:
        return TransactionCoordinator(batch_path.parent.parent / ".transactions", batches_root=batch_path.parent)

    def run_batch_sync(self, batch_path: Path, operation: Callable[[], T]) -> T:
        try:
            canonical = self._canonical_path(batch_path)
            return self._transactions(canonical).run_sync([Resource.batch(str(canonical))], _protected(operation))
        except _BatchFailure as exc:
            raise exc.error from None

    async def run_batch_async(self, batch_path: Path, operation: Callable[[], T]) -> T:
        try:
            canonical = await asyncio.to_thread(self._canonical_path, batch_path)
            return await self._transactions(canonical).run_async([Resource.batch(str(canonical))], _protected(operation))
        except _BatchFailure as exc:
            raise exc.error from None

    async def reserve_batch_async(self, batch_name: str, *, allow: Optional[Callable[[], bool]] = None) -> bool:
        """Reserve for the bulk caller off-loop; undo only our own unscheduled reservation."""
        owned = False

        def reserve() -> bool:
            nonlocal owned
            if allow is not None and not allow():
                return False
            owned = self.acquire_batch_lock(batch_name)
            return owned

        try:
            return await self.run_batch_async(self.get_batch_path(batch_name), reserve)
        except BaseException:
            if owned:
                self.release_batch_lock(batch_name)
            raise

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

    def _registry_coordinator(self):
        return self._transactions(self._canonical_path(self.batches_dir) / ".registry-anchor")

    @staticmethod
    def _validate_history(data):
        if not isinstance(data, list):
            raise RegistryError()
        names = set()
        for entry in data:
            if not isinstance(entry, dict) or not isinstance(entry.get("batch_name"), str):
                raise RegistryError()
            name = entry["batch_name"]
            try:
                validate_batch_name(name)
            except ValueError:
                raise RegistryError() from None
            if name in names:
                raise RegistryError()
            names.add(name)
            for key in ("custom_name", "created_at", "completed_at", "purged_at"):
                if entry.get(key) is not None and not isinstance(entry[key], str):
                    raise RegistryError()
            if "fields" in entry and (not isinstance(entry["fields"], list) or any(not isinstance(v, str) for v in entry["fields"])):
                raise RegistryError()
            if "status" in entry and not isinstance(entry["status"], str):
                raise RegistryError()

    def _mutate_history(self, change):
        def commit():
            history = self._read_history_raw()
            result = change(history)
            if result is not False:
                self._persist_history(history)
            return result
        return self._registry_coordinator().run_sync([Resource.history()], commit)

    def _record_history(self, batch_name: str, custom_name: str, fields: Optional[List[str]] = None):
        self._mutate_history(lambda history: history.append({
            "batch_name": batch_name, "custom_name": custom_name,
            "created_at": datetime.now().isoformat(), "status": "uploaded",
            "progress": 0, "fields": fields or settings.FIELD_KEYS,
        }))

    def update_batch_status(self, batch_name: str, status: str) -> None:
        def update(history):
            for entry in history:
                if entry["batch_name"] == batch_name:
                    entry["status"] = status
                    if status == "completed" and not entry.get("completed_at"):
                        entry["completed_at"] = datetime.now().isoformat()
                    return True
            return False
        self._mutate_history(update)

    def get_history(self) -> list:
        """Read batches.json and return enriched batch history entries."""
        history = self._read_history_raw()

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

            # Never delete a batch while OCR is running.
            if self.is_run_active(batch_name):
                raise RuntimeError(
                    f"Batch '{batch_name}' cannot be deleted while OCR is running"
                )

            def delete_history():
                history = self._read_history_raw()

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

                self._persist_history(history)

                # Remove stale WebSocket progress after successful deletion.
                ws_manager.clear_state(batch_name)

                return True

            return self._registry_coordinator().run_sync([Resource.history()], delete_history)

    def _read_history_raw(self) -> list:
        return read_registry(Path(settings.BATCHES_HISTORY_FILE), self._validate_history)

    def _persist_history(self, history: list) -> None:
        write_registry(Path(settings.BATCHES_HISTORY_FILE), history, self._validate_history)

    def _write_history_raw(self, history: list) -> None:
        # Explicit complete replacement, not an RMW API. Production mutations
        # use _mutate_history or the gate-protected deletion callbacks.
        self._registry_coordinator().run_sync([Resource.history()], lambda: self._replace_history(history))

    def _replace_history(self, history):
        self._read_history_raw()  # Never replace a corrupt existing registry.
        self._persist_history(history)

    def is_run_active(self, batch_name: str) -> bool:
        """True while an OCR run holds the batch lock (never purge such a batch)."""
        return self.retry_recovery_required(batch_name) or self._lock_path(batch_name).exists()

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

            def purge_history():
                batch_path = self.batches_dir / batch_name
                existed = batch_path.exists()

                history = self._read_history_raw()  # Validate before any existing filesystem deletion.
                if existed:
                    shutil.rmtree(str(batch_path))

                # Retain minimal history information for accountability.
                changed = False

                for entry in history:
                    if entry.get("batch_name") == batch_name:
                        entry["status"] = "purged"
                        entry["purged_at"] = datetime.now().isoformat()
                        entry.pop("files_count", None)
                        changed = True
                        break

                if changed:
                    self._persist_history(history)

                # Remove stale WebSocket progress after successful purge.
                if existed:
                    ws_manager.clear_state(batch_name)

                return existed

            return self._registry_coordinator().run_sync([Resource.history()], purge_history)

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

    def retry_recovery_required(self, batch_name: str) -> bool:
        return (self.get_batch_path(batch_name) / ".retry-recovery.json").exists()

    @staticmethod
    def _digest(path: Path) -> str:
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()

    def begin_retry_preparation(self, batch_name: str, files: List[Path], checkpoint_after: Optional[Dict[str, Any]] = None) -> None:
        """Write-ahead recovery intent: do not move any image before this saves."""
        path = self.get_batch_path(batch_name)
        checkpoint = path / "checkpoint.json"
        original = self._digest(checkpoint) if checkpoint.exists() else None
        atomic_write_json(path / ".retry-recovery.json", {
            "code": "retry_recovery_required", "version": 1,
            "checkpoint_sha256": original,
            "prepared_checkpoint_sha256": (
                hashlib.sha256(json.dumps(checkpoint_after, sort_keys=True).encode()).hexdigest()
                if checkpoint_after is not None else None
            ),
            "images": {f.name: self._digest(f) for f in files},
        })

    def finish_retry_preparation(self, batch_name: str) -> None:
        (self.get_batch_path(batch_name) / ".retry-recovery.json").unlink()

    def recover_retry(self, batch_name: str, *, prepared: bool = False) -> None:
        """Offline administrator only: workers stopped, BatchGate before operations lock."""
        self.run_batch_sync(self.get_batch_path(batch_name), lambda: self._recover_retry(batch_name, prepared=prepared))

    def _recover_retry(self, batch_name: str, *, prepared: bool = False) -> None:
        """Offline administrator only: verify original or prepared state.

        Default verifies restored originals; prepared=True explicitly accepts
        the recorded prepared checkpoint and root images. Stop all workers
        first. This does not move, recreate or repair data.
        A recovery marker is not a worker ownership/transaction protocol.
        """
        with self._batch_operations_lock():
            path = self.get_batch_path(batch_name)
            marker = path / ".retry-recovery.json"
            state = json.loads(marker.read_text(encoding="utf-8"))
            if not isinstance(state, dict) or set(state) != {"code", "version", "checkpoint_sha256", "prepared_checkpoint_sha256", "images"}:
                raise ValueError("Invalid retry recovery record")
            if state["code"] != "retry_recovery_required" or state["version"] != 1 or not isinstance(state["images"], dict):
                raise ValueError("Invalid retry recovery record")
            digests = [state["checkpoint_sha256"], state["prepared_checkpoint_sha256"]]
            if any(d is not None and (not isinstance(d, str) or not re.fullmatch(r"[0-9a-f]{64}", d)) for d in digests):
                raise ValueError("Invalid retry recovery digest")
            if any(not isinstance(d, str) or not re.fullmatch(r"[0-9a-f]{64}", d) for d in state["images"].values()):
                raise ValueError("Invalid retry recovery digest")
            checkpoint = path / "checkpoint.json"
            expected = state.get("checkpoint_sha256")
            if prepared and state.get("prepared_checkpoint_sha256"):
                results, audit = read_checkpoint(checkpoint)
                actual = hashlib.sha256(json.dumps({"results": results, "audit": audit}, sort_keys=True).encode()).hexdigest()
                if actual != state["prepared_checkpoint_sha256"]:
                    raise ValueError("Retry checkpoint does not match prepared state")
            elif expected is None:
                if checkpoint.exists():
                    raise ValueError("Retry checkpoint does not match original state")
            else:
                read_checkpoint(checkpoint)
                if self._digest(checkpoint) != expected:
                    raise ValueError("Retry checkpoint does not match original state")
            for name, digest in state["images"].items():
                validate_filename(name)
                expected_image = path / name if prepared else path / "_errors" / name
                other = path / "_errors" / name if prepared else path / name
                if other.exists() or self._digest(expected_image) != digest:
                    raise ValueError("Retry image does not match recovery state")
            # Keep the marker until the ordinary lock has been removed. A
            # failed removal must not make the inconsistent batch startable.
            self._lock_path(batch_name).unlink(missing_ok=True)
            marker.unlink()

    def acquire_batch_lock(self, batch_name: str) -> bool:
        """Low-level reservation, coordinated with deletion.

        Application starts/retries call this inside run_batch_async's gate;
        the bulk caller uses reserve_batch_async. No provider work belongs here.
        """
        validate_batch_name(batch_name)

        with self._batch_operations_lock():
            if self.retry_recovery_required(batch_name):
                return False
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
                try:
                    os.write(fd, str(os.getpid()).encode())
                finally:
                    os.close(fd)
            except Exception:
                # We created this reservation under the operations lock; no
                # caller has received ownership yet and no OCR is scheduled.
                lock.unlink(missing_ok=True)
                raise

            return True

    def release_batch_lock(self, batch_name: str) -> None:
        """Remove the run lockfile if present (safe to call unconditionally)."""
        if self.retry_recovery_required(batch_name):
            return
        try:
            self._lock_path(batch_name).unlink(missing_ok=True)
        except OSError:
            pass

batch_manager = BatchManager()
