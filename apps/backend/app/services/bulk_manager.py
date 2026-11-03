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
import copy
import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.atomic_io import atomic_write_json
from app.core.config import settings
from app.core.error_reporting import report_error
from app.core.security import validate_session_id, validate_batch_name
from app.core.transactions import Resource, TransactionError
from app.services.batch_manager import batch_manager, _protected, _BatchFailure

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


class BulkStateError(TransactionError):
    code = "bulk_state_invalid"


class BulkReadError(BulkStateError):
    code = "bulk_state_unreadable"


class BulkWriteError(BulkStateError):
    code = "bulk_state_write_failed"


class BulkRevisionConflict(BulkStateError):
    code = "bulk_revision_conflict"


class BulkManager:
    """Create, read and atomically update bulk-run state on disk."""

    def __init__(self, runs_dir: Optional[str] = None):
        self.runs_dir = Path(runs_dir or settings.BULK_RUNS_DIR)

    # ------------------------------------------------------------------ paths
    def _ensure_runs_dir(self) -> Path:
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        return self.runs_dir

    def run_dir(self, bulk_run_id: str) -> Path:
        """Directory for a run. The id is validated as a uuid4, so it can never
        be a traversal payload (reuses the existing session-id validator)."""
        validate_session_id(bulk_run_id)
        return self.runs_dir / str(uuid.UUID(bulk_run_id))

    def _run_json(self, bulk_run_id: str) -> Path:
        return self.run_dir(bulk_run_id) / "run.json"

    def export_csv_path(self, bulk_run_id: str) -> Path:
        return self.run_dir(bulk_run_id) / "consolidated.csv"

    def failures_csv_path(self, bulk_run_id: str) -> Path:
        return self.run_dir(bulk_run_id) / "failures.csv"

    def _resources(self, bulk_run_id, batch_names=()):
        path = batch_manager._canonical_path(self.run_dir(bulk_run_id))
        resources = list({Resource.batch(str(batch_manager._canonical_path(batch_manager.get_batch_path(name)))) for name in set(batch_names)})
        return resources + [Resource.bulk(str(path))]

    @staticmethod
    def _batches(run):
        return {f["batch_name"] for f in (run or {}).get("folders", []) if f.get("batch_name")}

    def _transaction(self, bulk_run_id, operation, *, with_batches=False, batch_names=()):
        names = set(batch_names) | (self._batches(self.get_run(bulk_run_id)) if with_batches else set())
        def invoke():
            current = self.get_run(bulk_run_id)
            if with_batches and not self._batches(current).issubset(names):
                raise BulkRevisionConflict()
            return operation(current)
        try:
            return batch_manager._registry_coordinator().run_sync(self._resources(bulk_run_id, names), _protected(invoke))
        except _BatchFailure as exc:
            raise exc.error from None

    async def mutate_async(self, bulk_run_id, operation, *, with_batches=False, batch_names=(), consume_stop=False):
        # Resolve paths/read the candidate batch set off-loop, before acquiring
        # the ordered Batch -> Bulk resource set. Recheck associations in-gate.
        from app.api.api_v1.endpoints.batches import _joined_calculation
        names = await _joined_calculation(lambda: set(batch_names) | (self._batches(self.get_run(bulk_run_id)) if with_batches else set()))
        resources = await _joined_calculation(lambda: self._resources(bulk_run_id, names))
        def invoke():
            run = self.get_run(bulk_run_id)
            if run is None:
                raise LookupError(bulk_run_id)
            if with_batches and not self._batches(run).issubset(names):
                raise BulkRevisionConflict()
            previous = copy.deepcopy(run)
            result = operation(run)
            self._retain_latches(previous, run, consume_stop=consume_stop)
            self._persist_run(run)
            return run, result
        try:
            return await batch_manager._registry_coordinator().run_async(resources, _protected(invoke))
        except _BatchFailure as exc:
            raise exc.error from None

    def mutate(self, bulk_run_id, operation, *, with_batches=False, consume_stop=False):
        def invoke(run):
            if run is None:
                return None
            previous = copy.deepcopy(run)
            operation(run)
            self._retain_latches(previous, run, consume_stop=consume_stop)
            self._persist_run(run)
            return run
        return self._transaction(bulk_run_id, invoke, with_batches=with_batches)

    @staticmethod
    def _validate(run, bulk_run_id):
        if not isinstance(run, dict) or run.get("bulk_run_id") != str(uuid.UUID(bulk_run_id)) or run.get("status") not in RUN_STATUSES or not isinstance(run.get("folders"), list):
            raise BulkStateError()
        names = set()
        for folder in run["folders"]:
            if not isinstance(folder, dict) or not isinstance(folder.get("source_folder"), str) or folder["source_folder"] in names:
                raise BulkStateError()
            names.add(folder["source_folder"])
            if folder.get("status") not in {FOLDER_PENDING, FOLDER_RUNNING, FOLDER_COMPLETED, FOLDER_COMPLETED_WITH_ERRORS, FOLDER_FAILED, FOLDER_SKIPPED}:
                raise BulkStateError()
            batch = folder.get("batch_name")
            if batch is not None:
                try:
                    validate_batch_name(batch)
                except (ValueError, TypeError, AttributeError):
                    raise BulkStateError() from None
            if any(folder.get(key) is not None and not isinstance(folder[key], str) for key in ("error", "integrity_error")):
                raise BulkStateError()
            for key in ("images_total", "images_processed", "images_failed"):
                if not isinstance(folder.get(key, 0), int) or isinstance(folder.get(key, 0), bool) or folder.get(key, 0) < 0:
                    raise BulkStateError()
        if any(not isinstance(run.get(k, False), bool) for k in ("pause_requested", "cancel_requested")):
            raise BulkStateError()

    @classmethod
    def _retain_latches(cls, previous, run, *, consume_stop=False):
        if not consume_stop:
            for key in ("pause_requested", "cancel_requested"):
                run[key] = bool(previous.get(key) or run.get(key))
        known = {f["source_folder"]: f for f in previous.get("folders", [])}
        for folder in run.get("folders", []):
            old = known.get(folder["source_folder"], {})
            if cls.folder_integrity_error(old):
                folder["integrity_error"] = cls.folder_integrity_error(old)
                folder["images_processed"] = old.get("images_processed", 0)
                folder["images_failed"] = old.get("images_failed", 0)
        for name, old in known.items():
            if cls.folder_integrity_error(old) and not any(f["source_folder"] == name for f in run["folders"]):
                run["folders"].append(copy.deepcopy(old))

    def _persist_run(self, run):
        self._validate(run, run["bulk_run_id"])
        self.apply_integrity_state(run)
        self.recount_progress(run)
        data = {k: v for k, v in run.items() if k != "_revision"}
        self._validate(data, run["bulk_run_id"])
        try:
            payload = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
            atomic_write_json(self._run_json(run["bulk_run_id"]), data, allow_nan=False)
            run["_revision"] = hashlib.sha256(payload).hexdigest()
        except Exception:
            raise BulkWriteError() from None

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
        field_groups: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Persist a new run in status ``queued``.

        *folders* is the ordered selection: ``[{"source_folder": str,
        "images_total": int}, ...]``. Processing order is this list's order and
        never changes, which is what makes the consolidated CSV deterministic.

        *schema_fields* is FROZEN here (plan decision D8): a later edit to the
        template must not shift CSV columns halfway through a 14,000-card run.
        *field_groups* is frozen for the same reason — it also carries each
        group's ``max_items``, which fixes the consolidated CSV's width without a
        pre-pass over the collection.
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
            "field_groups": field_groups,
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
        run["output_csv"] = str(self.export_csv_path(bulk_run_id))
        self._ensure_runs_dir()
        self.run_dir(bulk_run_id).mkdir(parents=True, exist_ok=False)
        self.save_run(run)
        return run

    # ------------------------------------------------------------------- read
    def get_run(self, bulk_run_id: str) -> Optional[Dict[str, Any]]:
        """Return an atomic snapshot; absence is None, corruption/I/O raise safe errors."""
        try:
            path = self._run_json(bulk_run_id)
        except ValueError:
            return None
        try:
            payload = path.read_bytes()
            def unique(pairs):
                data = {}
                for key, value in pairs:
                    if key in data:
                        raise BulkStateError()
                    data[key] = value
                return data
            def invalid_constant(_):
                raise BulkStateError()
            data = json.loads(payload, object_pairs_hook=unique, parse_constant=invalid_constant)
        except FileNotFoundError:
            return None
        except (ValueError, UnicodeError):
            raise BulkStateError() from None
        except OSError:
            raise BulkReadError() from None
        self._validate(data, bulk_run_id)
        data["_revision"] = hashlib.sha256(payload).hexdigest()
        return data

    def list_runs(self) -> List[Dict[str, Any]]:
        """All runs, newest first. Unreadable states are errors, never hidden emptiness."""
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
        def save(previous):
            if previous is not None and run.get("_revision") != previous.get("_revision"):
                raise BulkRevisionConflict()
            candidate = copy.deepcopy(run)
            self._retain_latches(previous or {}, candidate)
            self._persist_run(candidate)
            run.clear()
            run.update(candidate)
        self._transaction(run["bulk_run_id"], save)

    @staticmethod
    def folder_integrity_error(folder: Dict[str, Any]) -> Optional[str]:
        code = folder.get("integrity_error")
        if code:
            return str(code)
        # Earlier SAR-03b states recorded a fixed diagnostic but no latch.
        # Failed/unimported historical folders without that evidence stay valid.
        error = folder.get("error") or ""
        if error.startswith("Checkpoint unavailable ("):
            return "checkpoint_invalid"
        return None

    @staticmethod
    def apply_integrity_state(run: Dict[str, Any]) -> None:
        failed = False
        for folder in run.get("folders", []):
            code = BulkManager.folder_integrity_error(folder)
            if code:
                folder["integrity_error"] = code
                failed = True
                folder["status"] = FOLDER_FAILED
                folder["error"] = "Checkpoint integrity recovery required; counts are last known, not verified."
        run["checkpoint_error"] = failed
        if failed:
            run["status"] = STATUS_FAILED
            reason = "Batch no longer exists or was deleted. Re-import the source folder. " if run.get("error_code") == "batch_missing" else ""
            run["error"] = reason + "Checkpoint integrity recovery required; counts are last known, not verified."

    def recover_folder_integrity(self, bulk_run_id: str, source_folder: str) -> Dict[str, Any]:
        """Offline administrative operation, never exposed as a public endpoint.

        The operator restores the association/checkpoint first. No data repair
        is performed here. Stop all workers before invoking this operation.
        """
        from app.core.checkpoint import CheckpointInvalidError, read_checkpoint, completed_filenames
        from app.services.batch_manager import batch_manager

        def recover(run):
            if run is None or self.is_any_run_active() or run.get("status") == STATUS_RUNNING:
                raise RuntimeError("Bulk recovery requires an inactive run")
            folder = next(f for f in run["folders"] if f["source_folder"] == source_folder)
            batch = folder.get("batch_name")
            if not self.folder_integrity_error(folder) or not batch or batch_manager.is_run_active(batch):
                raise CheckpointInvalidError()
            results, _ = read_checkpoint(batch_manager.get_batch_path(batch) / "checkpoint.json")
            folder["images_processed"] = len(results)
            folder["images_failed"] = len(results) - len(completed_filenames(results))
            folder.pop("integrity_error", None)
            folder.update(status=FOLDER_PENDING, error=None)
            run.update(status=STATUS_PAUSED, error=None, error_code=None)
            self.apply_integrity_state(run)
            self.recount_progress(run)
            self._persist_run(run)
            return run

        return self._transaction(bulk_run_id, recover, with_batches=True)

    def update_run(self, bulk_run_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
        """Read-modify-write the named top-level fields atomically."""
        def update(run):
            if run.get("status") in TERMINAL_STATUSES and not run.get("checkpoint_error") and fields.get("status", run["status"]) != run["status"]:
                raise BulkRevisionConflict()
            # Stop flags are latches. Only the explicit start/resume transition
            # consumes them; ordinary worker updates cannot clear requests.
            values = dict(fields)
            for key in ("pause_requested", "cancel_requested"):
                values[key] = bool(run.get(key) or values.get(key))
            run.update(values)
        return self.mutate(bulk_run_id, update)

    def update_folder(self, bulk_run_id: str, source_folder: str, **fields: Any) -> Optional[Dict[str, Any]]:
        def update(run):
            if (run["status"] in TERMINAL_STATUSES or run["status"] in {STATUS_PAUSED, STATUS_INTERRUPTED}) and not run.get("checkpoint_error"):
                return
            for folder in run["folders"]:
                if folder["source_folder"] == source_folder:
                    folder.update(fields)
                    break
        return self.mutate(bulk_run_id, update)

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
            try:
                payload = f"{bulk_run_id}:{os.getpid()}".encode()
                if os.write(fd, payload) != len(payload):
                    raise OSError("bulk_reservation_write_failed")
            finally:
                os.close(fd)
        except Exception:
            try:
                lock.unlink(missing_ok=True)
            except OSError:
                pass
            raise BulkWriteError() from None
        return True

    def release_run_lock(self, expected_id: Optional[str] = None) -> None:
        """Drop the single-run lock (safe to call unconditionally)."""
        try:
            if expected_id is not None and self.locked_run_id() != expected_id:
                return
            self._lock_path().unlink(missing_ok=True)
        except OSError as exc:
            report_error(logger, "bulk_lock_release_failed", "bulk.lock.release", exc)
            raise BulkWriteError() from None

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
    def _release_interrupted_batch_lock(self, batch_name: Optional[str]) -> None:
        """Release the per-batch run lock held by a bulk run's in-flight batch.

        Scoped deliberately to the batch a bulk run recorded as current, rather
        than sweeping every ``.run.lock`` on disk: that would change behaviour
        for the interactive single-batch workflow, and on a multi-worker
        deployment could steal a lock another worker is legitimately holding.
        """
        if not batch_name:
            return
        # Imported here: batch_manager imports config/security, and importing it
        # at module scope would tie this module's import order to it.
        from app.services.batch_manager import batch_manager

        try:
            if batch_manager.retry_recovery_required(batch_name):
                logger.warning("Retaining batch recovery lock; administrative verification required")
                return
            if batch_manager.is_run_active(batch_name):
                logger.info(
                    "Releasing stale run lock on batch %s left by a previous process",
                    batch_name,
                )
                batch_manager.release_batch_lock(batch_name)
        except (OSError, ValueError):
            logger.warning("Could not release stale run lock on batch %s", batch_name)

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
        for candidate in self.list_runs():
            bulk_run_id = candidate["bulk_run_id"]
            def interrupt(run):
                if run["status"] != STATUS_RUNNING:
                    return
                run.update(status=STATUS_INTERRUPTED, interrupted_at=_now(), pause_requested=False, cancel_requested=False)
                for folder in run["folders"]:
                    if folder["status"] == FOLDER_RUNNING:
                        folder["status"] = FOLDER_PENDING
                self._release_interrupted_batch_lock(run.get("current_batch_id"))
                marked.append(bulk_run_id)
            self.mutate(bulk_run_id, interrupt, with_batches=True, consume_stop=True)
        # Existing offline-startup assumption only; no live-worker recovery.
        if self.is_any_run_active():
            self.release_run_lock()
        return marked


bulk_manager = BulkManager()
