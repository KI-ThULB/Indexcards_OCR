"""Persistent state for bulk / multi-batch runs.

A bulk run is *orchestration state only*: which source folders were selected,
which internal batch each became, and how far the run got. The extracted
metadata itself stays where it always was — in each batch's own
``checkpoint.json``. This module never duplicates the checkpoint system; it
records the order of folders and the progress across them so a run can be
resumed after a pause or a backend restart.

Layout — one directory per run::

    data/bulk_runs/<bulk_run_id>/run.json          # this module
    data/bulk_runs/<bulk_run_id>/consolidated.csv  # bulk_export
    data/bulk_runs/<bulk_run_id>/failures.csv      # bulk_export

``run.json`` holds no extracted metadata and no personal data — only folder
names, counts, timestamps and the selected provider/model.

Two safety properties matter here:

1. **Atomic writes.** State is rewritten after every folder (and every progress
   tick), so a truncated ``run.json`` would strand a 14,000-card run. Writes go
   through :func:`app.core.atomic_io.atomic_write_json`.
2. **No auto-resume after a restart** (plan decision D2). The orchestrator is an
   in-process asyncio task, so a restart necessarily interrupts a run. On startup
   :func:`BulkManager.mark_interrupted_runs` marks any run still recorded as
   ``running`` as ``interrupted`` and stops there. Nothing re-sends images to the
   model until a human clicks Resume — an unattended crash-loop or a routine
   redeploy must never silently restart VLM spend.
"""
import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.atomic_io import atomic_write_json
from app.core.config import settings
from app.core.security import validate_session_id

logger = logging.getLogger(__name__)

# ── Run statuses ─────────────────────────────────────────────────────────────
STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_PAUSED = "paused"
STATUS_INTERRUPTED = "interrupted"          # backend died mid-run; needs explicit Resume (D2)
STATUS_COMPLETED = "completed"
STATUS_COMPLETED_WITH_ERRORS = "completed_with_errors"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

RUN_STATUSES = frozenset({
    STATUS_QUEUED, STATUS_RUNNING, STATUS_PAUSED, STATUS_INTERRUPTED,
    STATUS_COMPLETED, STATUS_COMPLETED_WITH_ERRORS, STATUS_FAILED, STATUS_CANCELLED,
})
# Statuses a Resume may start from.
RESUMABLE_STATUSES = frozenset({STATUS_PAUSED, STATUS_INTERRUPTED, STATUS_QUEUED})
# Statuses that mean "this run is finished, for better or worse".
TERMINAL_STATUSES = frozenset({
    STATUS_COMPLETED, STATUS_COMPLETED_WITH_ERRORS, STATUS_FAILED, STATUS_CANCELLED,
})

# ── Per-folder statuses ──────────────────────────────────────────────────────
FOLDER_PENDING = "pending"
FOLDER_RUNNING = "running"
FOLDER_COMPLETED = "completed"
FOLDER_COMPLETED_WITH_ERRORS = "completed_with_errors"
FOLDER_FAILED = "failed"
FOLDER_SKIPPED = "skipped"

# A folder in one of these states is done and must never be re-processed.
FOLDER_DONE_STATUSES = frozenset({
    FOLDER_COMPLETED, FOLDER_COMPLETED_WITH_ERRORS, FOLDER_SKIPPED,
})

_LOCK_FILENAME = ".bulk_run.lock"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BulkManager:
    """Create, read and atomically update bulk-run state on disk."""

    def __init__(self, runs_dir: Optional[str] = None):
        self.runs_dir = Path(runs_dir or settings.BULK_RUNS_DIR)
        # Serialises read-modify-write cycles within this process. The single-run
        # lock below is what prevents two *runs* executing at once.
        self._mutate_lock = threading.Lock()

    # ------------------------------------------------------------------ paths
    def _ensure_runs_dir(self) -> Path:
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        return self.runs_dir

    def run_dir(self, bulk_run_id: str) -> Path:
        """Directory for a run. The id is validated as a uuid4, so it can never
        be a traversal payload (reuses the existing session-id validator)."""
        validate_session_id(bulk_run_id)
        return self.runs_dir / bulk_run_id

    def _run_json(self, bulk_run_id: str) -> Path:
        return self.run_dir(bulk_run_id) / "run.json"

    def export_csv_path(self, bulk_run_id: str) -> Path:
        return self.run_dir(bulk_run_id) / "consolidated.csv"

    def failures_csv_path(self, bulk_run_id: str) -> Path:
        return self.run_dir(bulk_run_id) / "failures.csv"

    # ----------------------------------------------------------------- create
    def create_run(
        self,
        *,
        name: str,
        template_id: str,
        schema_fields: List[str],
        provider: str,
        model: Optional[str],
        folders: List[Dict[str, Any]],
        prompt_template: Optional[str] = None,
        field_rules: Optional[Dict[str, Any]] = None,
        authority_bindings: Optional[Dict[str, Any]] = None,
        describe_pictures: bool = False,
    ) -> Dict[str, Any]:
        """Persist a new run in status ``queued``.

        *folders* is the ordered selection: ``[{"source_folder": str,
        "images_total": int}, ...]``. Processing order is this list's order and
        never changes, which is what makes the consolidated CSV deterministic.

        *schema_fields* is FROZEN here (plan decision D8): a later edit to the
        template must not shift CSV columns halfway through a 14,000-card run.
        *name* is a display label only and is NEVER used as a filesystem path.
        """
        bulk_run_id = str(uuid.uuid4())
        run = {
            "bulk_run_id": bulk_run_id,
            "name": name,
            "template_id": template_id,
            "schema_fields": list(schema_fields),
            "prompt_template": prompt_template,
            "field_rules": field_rules,
            "authority_bindings": authority_bindings,
            "describe_pictures": bool(describe_pictures),
            "provider": provider,
            "model": model,
            "created_at": _now(),
            "started_at": None,
            "completed_at": None,
            "interrupted_at": None,
            "status": STATUS_QUEUED,
            "folders_total": len(folders),
            "folders_completed": 0,
            "images_total": sum(int(f.get("images_total", 0)) for f in folders),
            "images_processed": 0,
            "images_failed": 0,
            "current_folder": None,
            "current_batch_id": None,
            "last_image": None,
            "error": None,
            "pause_requested": False,
            "cancel_requested": False,
            "folders": [
                {
                    "source_folder": f["source_folder"],
                    "batch_name": None,
                    "status": FOLDER_PENDING,
                    "images_total": int(f.get("images_total", 0)),
                    "images_processed": 0,
                    "images_failed": 0,
                    "started_at": None,
                    "completed_at": None,
                    "error": None,
                }
                for f in folders
            ],
        }
        self._ensure_runs_dir()
        self.run_dir(bulk_run_id).mkdir(parents=True, exist_ok=False)
        atomic_write_json(self._run_json(bulk_run_id), run)
        return run

    # ------------------------------------------------------------------- read
    def get_run(self, bulk_run_id: str) -> Optional[Dict[str, Any]]:
        """Return a run's state, or None if it does not exist / is unreadable."""
        try:
            path = self._run_json(bulk_run_id)
        except ValueError:
            return None
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            logger.exception("Unreadable bulk run state at %s", path)
            return None
        return data if isinstance(data, dict) else None

    def list_runs(self) -> List[Dict[str, Any]]:
        """All runs, newest first. Unreadable entries are skipped, not fatal."""
        if not self.runs_dir.exists():
            return []
        runs: List[Dict[str, Any]] = []
        for entry in self.runs_dir.iterdir():
            if not entry.is_dir():
                continue
            run = self.get_run(entry.name)
            if run:
                runs.append(run)
        runs.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
        return runs

    # ----------------------------------------------------------------- update
    def save_run(self, run: Dict[str, Any]) -> None:
        """Atomically persist a full run state object."""
        atomic_write_json(self._run_json(run["bulk_run_id"]), run)

    def update_run(self, bulk_run_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
        """Read-modify-write the named top-level fields atomically."""
        with self._mutate_lock:
            run = self.get_run(bulk_run_id)
            if run is None:
                return None
            run.update(fields)
            self.save_run(run)
            return run

    def update_folder(
        self, bulk_run_id: str, source_folder: str, **fields: Any
    ) -> Optional[Dict[str, Any]]:
        """Read-modify-write one folder entry (matched by source folder name)."""
        with self._mutate_lock:
            run = self.get_run(bulk_run_id)
            if run is None:
                return None
            for folder in run.get("folders", []):
                if folder.get("source_folder") == source_folder:
                    folder.update(fields)
                    break
            else:
                return run
            self.save_run(run)
            return run

    def recount_progress(self, run: Dict[str, Any]) -> Dict[str, Any]:
        """Recompute the run-level counters from the per-folder entries.

        Derived rather than incremented, so a resume cannot double-count images
        that were already tallied before the interruption.
        """
        folders = run.get("folders", [])
        run["folders_completed"] = sum(
            1 for f in folders if f.get("status") in FOLDER_DONE_STATUSES
        )
        run["images_processed"] = sum(int(f.get("images_processed", 0)) for f in folders)
        run["images_failed"] = sum(int(f.get("images_failed", 0)) for f in folders)
        return run

    # ------------------------------------------------- single-run lock (O_EXCL)
    def _lock_path(self) -> Path:
        return self._ensure_runs_dir() / _LOCK_FILENAME

    def acquire_run_lock(self, bulk_run_id: str) -> bool:
        """Atomically claim the right to be the one executing bulk run.

        Mirrors ``BatchManager.acquire_batch_lock``: an ``O_EXCL`` create is
        atomic on a local filesystem, so this is correct across uvicorn workers
        on one host. Returns False when another run already holds it.
        """
        lock = self._lock_path()
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        try:
            os.write(fd, f"{bulk_run_id}:{os.getpid()}".encode())
        finally:
            os.close(fd)
        return True

    def release_run_lock(self) -> None:
        """Drop the single-run lock (safe to call unconditionally)."""
        try:
            self._lock_path().unlink(missing_ok=True)
        except OSError:
            pass

    def locked_run_id(self) -> Optional[str]:
        """The run id recorded in the lockfile, or None when unlocked."""
        try:
            raw = self._lock_path().read_text(encoding="utf-8")
        except OSError:
            return None
        return raw.split(":", 1)[0] or None

    def is_any_run_active(self) -> bool:
        return self._lock_path().exists()

    # ------------------------------------------------------- startup recovery
    def mark_interrupted_runs(self) -> List[str]:
        """Startup hook: mark runs that were ``running`` as ``interrupted``.

        The orchestrator lives in the process that just died, so nothing can
        still be executing. Each affected run keeps ``current_folder``,
        ``current_batch_id`` and ``last_image`` exactly as recorded, and gains an
        ``interrupted_at`` stamp, so the operator can verify where it stopped
        before choosing to resume.

        **No VLM processing is started here** (D2). Returns the ids marked.
        """
        marked: List[str] = []
        for run in self.list_runs():
            if run.get("status") != STATUS_RUNNING:
                continue
            run["status"] = STATUS_INTERRUPTED
            run["interrupted_at"] = _now()
            # Clear stale requests so a later Resume is not cancelled by them.
            run["pause_requested"] = False
            run["cancel_requested"] = False
            # A folder recorded as mid-flight is no longer running.
            for folder in run.get("folders", []):
                if folder.get("status") == FOLDER_RUNNING:
                    folder["status"] = FOLDER_PENDING
            try:
                self.save_run(run)
                marked.append(run["bulk_run_id"])
            except OSError:
                logger.exception("Could not mark bulk run %s interrupted", run.get("bulk_run_id"))

        # Any lock left behind belongs to the dead process — no orchestrator can
        # be holding it now, and keeping it would block every future run.
        if self.is_any_run_active():
            logger.info("Releasing stale bulk-run lock left by a previous process")
            self.release_run_lock()
        return marked


bulk_manager = BulkManager()
