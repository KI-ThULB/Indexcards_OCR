import json
import re
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from app.core.config import settings

class BatchManager:
    def __init__(self, data_dir: str = settings.DATA_DIR):
        self.data_dir = Path(data_dir)
        self.temp_dir = Path(settings.TEMP_DIR)
        self.batches_dir = Path(settings.BATCHES_DIR)
        
        # Ensure directories exist
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.batches_dir.mkdir(parents=True, exist_ok=True)

    def generate_session_id(self) -> str:
        return str(uuid.uuid4())

    def get_temp_session_path(self, session_id: str) -> Path:
        session_path = self.temp_dir / session_id
        session_path.mkdir(parents=True, exist_ok=True)
        return session_path

    def create_batch(
        self,
        custom_name: str,
        session_id: str,
        fields: Optional[List[str]] = None,
        prompt_template: Optional[str] = None,
        field_rules: Optional[Dict[str, dict]] = None,
        corrector_enabled: bool = False,
        corrector_cap: Optional[int] = 100,
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
            "corrector_enabled": corrector_enabled,
            "corrector_cap": corrector_cap,
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
        """Update the status field of a batch in batches.json."""
        history_file = Path(settings.BATCHES_HISTORY_FILE)
        if not history_file.exists():
            return
        try:
            with open(history_file, "r") as f:
                history = json.load(f)
            for entry in history:
                if entry.get("batch_name") == batch_name:
                    entry["status"] = status
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

        image_extensions = {".jpg", ".jpeg", ".png", ".tiff", ".tif"}
        enriched = []
        for entry in history:
            batch_name = entry.get("batch_name", "")
            batch_path = self.batches_dir / batch_name

            # files_count: count image files live if directory exists, else use stored value
            if batch_path.exists():
                files_count = len([
                    f for f in batch_path.iterdir()
                    if f.is_file() and f.suffix.lower() in image_extensions
                ])
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
        """Delete a batch directory and remove its entry from batches.json.
        Returns True if found and deleted, False if not found."""
        batch_path = self.batches_dir / batch_name
        history_file = Path(settings.BATCHES_HISTORY_FILE)

        # Load history
        history = []
        if history_file.exists():
            try:
                with open(history_file, "r") as f:
                    history = json.load(f)
            except Exception:
                history = []

        # Check if batch exists in history or on disk
        original_length = len(history)
        history = [e for e in history if e.get("batch_name") != batch_name]
        found_in_history = len(history) < original_length
        found_on_disk = batch_path.exists()

        if not found_in_history and not found_on_disk:
            return False

        # Delete directory if it exists
        if found_on_disk:
            shutil.rmtree(str(batch_path))

        # Save updated history
        with open(history_file, "w") as f:
            json.dump(history, f, indent=2)

        return True

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
        return self.batches_dir / batch_name

batch_manager = BatchManager()
