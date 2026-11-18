"""Sequential driver for a bulk run.

This module sits **above** the existing batch system. It owns no OCR logic, no
checkpoint format and no retry policy — it decides which folder runs next and
records how far the run got::

    BulkRun orchestrator (one folder at a time, in configured order)
      |- materialise source folder -> ordinary batch (bulk_import)
      |- acquire the existing per-batch lock
      |- run_ocr_task()  ->  ocr_engine.process_batch()
      |- the batch's own checkpoint.json is the resume unit, unchanged
      |- update run state, broadcast progress, lock released by run_ocr_task
      `- ... next folder ...

Folders run **sequentially** with no cross-folder parallelism (plan decision
D5): bounded VLM load, bounded RAM and file descriptors, simple recovery, and a
failure attributable to exactly one folder. The existing image-level pool inside
a batch (``MAX_WORKERS``) is untouched.

Retries are the existing ones. ``ocr_engine._call_vlm_api_resilient`` already
does bounded exponential backoff with jitter, honours ``Retry-After`` on 429,
retries 5xx/timeouts and gives up on other 4xx; it also re-asks once for an
unusable model response (empty, or complete-but-invalid JSON) — inside the same
``MAX_RETRIES`` budget, so that setting keeps meaning "requests in total".
Failed cards move to the batch's ``_errors/`` directory. Nothing here adds a
second retry loop — selective later retries use the existing
``/batches/{name}/retry`` endpoints.

Error classification
--------------------
*Recoverable* (image level): the folder finishes with ``images_failed > 0``. With
``BULK_CONTINUE_ON_BATCH_ERROR`` the run moves to the next folder and ends
``completed_with_errors``.

*Structural*: something that would invalidate every following folder — a missing
template or empty field list, a missing/invalid provider credential, an
unreachable import root or a folder that disappeared, a folder that yields zero
successful images (a configuration fault), or an unexpected exception. These stop
the whole run with status ``failed``.

Pause/cancel are cooperative and reuse the batch ``cancel_event``: processing
stops after the current image, whose checkpoint has already been saved, so no
completed result is ever lost. The engine checks the same event before every
attempt, so once a stop is registered no further request is issued — not even a
retry of the card in flight, and a card caught before it reached the model is
left completely untouched for the resume. The request already open is allowed to
run out; killing it is deliberately not attempted.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.core.transactions import TransactionTimeout
from app.core.audit import log_event
from app.core.error_reporting import report_error
from app.core.checkpoint import CheckpointError, CheckpointInvalidError, CheckpointReadError, completed_filenames, read_checkpoint
from app.core.config import settings
from app.services import bulk_import
from app.services.batch_manager import BatchMissingError, batch_manager
from app.services.bulk_manager import BulkStateError, BulkRevisionConflict
from app.services.bulk_manager import (
    FOLDER_COMPLETED,
    FOLDER_COMPLETED_WITH_ERRORS,
    FOLDER_DONE_STATUSES,
    FOLDER_FAILED,
    FOLDER_PENDING,
    FOLDER_RUNNING,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_COMPLETED_WITH_ERRORS,
    STATUS_FAILED,
    STATUS_PAUSED,
    STATUS_RUNNING,
    RESUMABLE_STATUSES,
    TERMINAL_STATUSES,
    bulk_manager,
)
from app.services.template_service import template_service
from app.services.ws_manager import ws_manager

logger = logging.getLogger(__name__)

# One asyncio task per executing run. Module-level so the task is not garbage
# collected mid-run, and so pause/cancel/status can find it. asyncio.create_task
# rather than BackgroundTasks: a run outlives the request that started it.
_tasks: Dict[str, asyncio.Task] = {}
_cancel_targets: Dict[str, Any] = {}

# Substrings that mark a provider *credential* problem rather than a bad card.
# A credential fault invalidates every following folder, so it stops the run.
_CREDENTIAL_MARKERS = (
    "api key missing",
    "ungültiger api key",
    "invalid api key",
    "401",
    "403",
    "unauthorized",
)

# Substrings that mark a provider *billing* refusal. Like a bad credential this
# applies to every remaining card, so it stops the run instead of failing
# hundreds of cards one by one against a provider that is refusing all of them.
# "http 402" rather than a bare "402" so a provider message that merely contains
# those digits cannot abort a healthy run.
_BILLING_MARKERS = (
    "http 402",
    "insufficient credit",
    "maximum cost",
    "add credits",
)

_PROVIDER_FAULT_MARKERS = _CREDENTIAL_MARKERS + _BILLING_MARKERS


def _provider_fault(error: Any) -> bool:
    """True when a card's error is a provider credential or billing refusal."""
    if not error:
        return False
    text = str(error).lower()
    return any(marker in text for marker in _PROVIDER_FAULT_MARKERS)


def _provider_host(provider: Optional[str]) -> str:
    """Host the run's provider resolves to, for the audit trail.

    Deferred import: batches.py imports service modules, so importing it at
    module scope here would create a cycle (same reason run_ocr_task is imported
    late). Host only — never a full URL — so no credential can reach the log.
    """
    try:
        from app.api.api_v1.endpoints.batches import provider_endpoint_host

        return provider_endpoint_host(provider)
    except Exception:  # pragma: no cover - auditing must never break a run
        return ""


class ReservationTimeout(TransactionTimeout):
    """Only a pre-OCR reservation timeout may leave a folder pending."""


class ReservationBusy(ReservationTimeout):
    code = "batch_processing_active"


class StructuralError(Exception):
    """A fault that would invalidate every following folder — stop the run."""

    def __init__(self, message: str, *, code: str = "bulk_failed") -> None:
        super().__init__(message)
        self.code = code


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_detail(detail: str, limit: int = 200) -> str:
    """Bound an error string before it is stored in run.json or shown in the UI.

    Provider and engine messages can embed a slice of the model's response, and
    run.json must stay free of extracted metadata and small enough to rewrite
    after every image. This helper only bounds text; it does not sanitize sensitive content.
    """
    text = " ".join(str(detail).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


# --------------------------------------------------------------------------- #
# Task registry
# --------------------------------------------------------------------------- #
def is_task_active(bulk_run_id: str) -> bool:
    task = _tasks.get(bulk_run_id)
    return task is not None and not task.done()


def active_run_ids() -> List[str]:
    return [rid for rid, t in _tasks.items() if not t.done()]


# --------------------------------------------------------------------------- #
# Progress accounting
# --------------------------------------------------------------------------- #
def _folder_counts_from_checkpoint(batch_name: Optional[str], *, required: bool = False) -> Tuple[int, int]:
    """Read current counts or raise. Only expected absence is a known zero."""
    if not batch_name:
        if required:
            raise CheckpointInvalidError()
        return 0, 0
    try:
        checkpoint = batch_manager.get_batch_path(batch_name) / "checkpoint.json"
    except ValueError:
        raise CheckpointInvalidError() from None
    try:
        results, _ = read_checkpoint(checkpoint)
    except FileNotFoundError:
        if not required:
            return 0, 0
        raise CheckpointReadError() from None
    except CheckpointError:
        raise
    except Exception:
        raise CheckpointReadError() from None
    succeeded = len(completed_filenames(results))
    failed = sum(1 for r in results if r.get("success") is not True)
    return succeeded + failed, failed


def _checkpoint_required(folder: Dict[str, Any]) -> bool:
    return bool(folder.get("images_processed") or folder.get("images_failed")) or folder.get("status") in {FOLDER_COMPLETED, FOLDER_COMPLETED_WITH_ERRORS} or bool(folder.get("batch_name") and folder.get("status") == FOLDER_FAILED)


def _reconcile_counts(run: Dict[str, Any]) -> Dict[str, Any]:
    """On integrity errors retain last-known counts, explicitly marked invalid."""
    run["checkpoint_error"] = False
    for folder in run.get("folders", []):
        # A never-materialised folder can be empty, but known counts or a
        # completed status always require a checkpoint association.
        if bulk_manager.folder_integrity_error(folder):
            folder["integrity_error"] = bulk_manager.folder_integrity_error(folder)
            run["checkpoint_error"] = True
            continue
        required = _checkpoint_required(folder)
        try:
            processed, failed = _folder_counts_from_checkpoint(folder.get("batch_name"), required=required)
        except CheckpointError as exc:
            report_error(logger, exc.code, "bulk.count", exc, event_id=run["bulk_run_id"])
            folder["integrity_error"] = exc.code
            folder["status"] = FOLDER_FAILED
            folder["error"] = f"Checkpoint unavailable ({exc.code}); counts are last known, not verified."
            run["checkpoint_error"] = True
            continue
        if folder.get("batch_name"):
            folder["images_processed"] = processed
            folder["images_failed"] = failed
    if run["checkpoint_error"]:
        run["status"] = STATUS_FAILED
        run["error"] = "Checkpoint unavailable; counts are last known, not verified."
    bulk_manager.apply_integrity_state(run)
    return bulk_manager.recount_progress(run)


# --------------------------------------------------------------------------- #
# Public controls
# --------------------------------------------------------------------------- #
async def _call(operation, *args, **kwargs):
    from app.api.api_v1.endpoints.batches import _joined_calculation
    value = await _joined_calculation(lambda: operation(*args, **kwargs))
    if getattr(operation, "__name__", "") in {"_finalise", "_classify_folder", "_refresh_and_emit"}:
        _emit_progress(args[0])
    return value


async def start_run(bulk_run_id: str, *, allowed_statuses=None) -> Dict[str, Any]:
    """Validate, claim and commit once; publish task only after successful commit."""
    current = bulk_manager.get_run(bulk_run_id)
    if current is None:
        raise LookupError(bulk_run_id)
    bulk_run_id = current["bulk_run_id"]
    if allowed_statuses is None and current["status"] in {STATUS_COMPLETED, STATUS_COMPLETED_WITH_ERRORS}:
        return current  # Compatibility: finished runs are a no-op, never replanned.
    if is_task_active(bulk_run_id):
        raise RuntimeError("This bulk run is already processing")
    owned = False
    allowed = RESUMABLE_STATUSES if allowed_statuses is None else allowed_statuses
    def begin(run):
        nonlocal owned
        _reconcile_counts(run)
        if run.get("checkpoint_error"):
            return False
        if run["status"] not in allowed or run.get("cancel_requested"):
            raise RuntimeError("Bulk run is not resumable")
        if not bulk_manager.acquire_run_lock(bulk_run_id):
            raise RuntimeError("Another bulk run is already processing")
        owned = True
        run.update(status=STATUS_RUNNING, started_at=run.get("started_at") or _now(),
                   interrupted_at=None, completed_at=None, error=None, error_code=None,
                   pause_requested=False, cancel_requested=False)
        return True
    try:
        run, ready = await bulk_manager.mutate_async(bulk_run_id, begin, with_batches=True, consume_stop=True)
        if not ready:
            _emit_progress(bulk_run_id)
            raise CheckpointReadError()
    except BaseException:
        if owned:
            def undo():
                def interrupt(current):
                    if current["status"] == STATUS_RUNNING:
                        if current.get("cancel_requested"):
                            current.update(status=STATUS_CANCELLED, completed_at=_now(),
                                           current_batch_id=None, current_folder=None)
                        elif current.get("pause_requested"):
                            current.update(status=STATUS_PAUSED, current_batch_id=None)
                        else:
                            current.update(status="interrupted", interrupted_at=_now())
                try:
                    bulk_manager.mutate(bulk_run_id, interrupt)
                finally:
                    bulk_manager.release_run_lock(bulk_run_id)
            await _call(undo)
        raise
    task = asyncio.create_task(_drive(bulk_run_id))
    _tasks[bulk_run_id] = task
    def observe(done):
        if not done.cancelled():
            error = done.exception()
            if error is not None:
                report_error(logger, "bulk_task_failed", "bulk.task", error, event_id=bulk_run_id)
    task.add_done_callback(observe)
    return run


def request_pause(bulk_run_id: str) -> bool:
    """Ask the run to stop after the current image. Returns False if unknown."""
    return _request_stop(bulk_run_id, pause=True)


def request_cancel(bulk_run_id: str) -> bool:
    """Ask the run to cancel after the current image. Returns False if unknown."""
    return _request_stop(bulk_run_id, pause=False)


async def request_stop_async(bulk_run_id: str, *, pause: bool) -> bool:
    accepted = await _call(_request_stop, bulk_run_id, pause=pause)
    _emit_progress(bulk_run_id)
    return accepted


def _request_stop(bulk_run_id: str, *, pause: bool) -> bool:
    current = bulk_manager.get_run(bulk_run_id)
    if current is None:
        return False
    bulk_run_id = current["bulk_run_id"]
    accepted = False
    target_event = None
    def stop(run):
        nonlocal accepted, target_event
        if run["status"] != STATUS_RUNNING:
            return
        run["pause_requested" if pause else "cancel_requested"] = True
        accepted = True
        target = _cancel_targets.get(bulk_run_id)
        target_event = target[1] if target is not None else None
    run = bulk_manager.mutate(bulk_run_id, stop)
    if run is None or not accepted:
        return False
    # Cooperative stop of the in-flight batch: process_batch checks the event
    # after each image, once that image's checkpoint has been written, and the
    # engine checks it again before any retry, so no further request goes out.
    if target_event is not None:
        target_event.set()  # Captured in-gate; never resolve a later run's event.
    # Publish immediately. Without this the last broadcast state still says
    # pause_requested=false, and the UI — which prefers the pushed state over an
    # HTTP response — kept showing a plain "running" run until the next image
    # finished. That was minutes, and it is why Pause and Cancel looked like
    # no-ops and were clicked repeatedly.
    _emit_progress(bulk_run_id)
    return True


# --------------------------------------------------------------------------- #
# The sequential driver
# --------------------------------------------------------------------------- #
async def _drive(bulk_run_id: str) -> None:
    """Process the run's folders one at a time, then finalise.

    Always leaves the run in a terminal, paused or interrupted state and always
    releases the single-run lock — a stuck lock would block every future run.
    """
    try:
        await _drive_folders(bulk_run_id)
    except ReservationTimeout as exc:
        # No OCR started: keep the folder pending, not failed (which would
        # incorrectly require a checkpoint for a never-started batch).
        report_error(logger, exc.code, "bulk.reserve", exc, event_id=bulk_run_id)
        run = bulk_manager.get_run(bulk_run_id)
        if run is not None:
            status = STATUS_CANCELLED if run.get("cancel_requested") else STATUS_PAUSED
            await _call(bulk_manager.update_run, bulk_run_id, error_code=exc.code)
            await _call(_finalise, bulk_run_id, status, error=f"Batch reservation unavailable ({exc.code}); resume explicitly.", preserve_stop=True, checkpoint_gate=False)
    except asyncio.CancelledError:
        # The process is going down. Leave the run as "running" so the startup
        # hook marks it interrupted and a human decides whether to resume (D2).
        logger.warning("Bulk run %s cancelled by the event loop", bulk_run_id)
        raise
    except Exception as e:
        code = e.code if isinstance(e, StructuralError) else "bulk_failed"
        messages = {
            "empty_fields": "The run has an empty field list.",
            "import_unavailable": "The import root is not configured or unreachable.",
            "template_missing": "The selected template no longer exists.",
            "import_failed": "Could not import the source folder.",
            "checkpoint_failed": "Could not read folder results.",
            "batch_failed": "Batch processing failed.",
            "no_extractions": "The folder produced no successful extractions. Check the configuration.",
            "provider_refused": "Provider refused the request (credential or billing). Check provider configuration.",
            "batch_missing": "Batch no longer exists or was deleted. Re-import the source folder.",
        }
        if code not in messages:
            code = "bulk_failed"
        error_message = messages.get(code, "Bulk processing failed. Check the configuration and retry.")
        report_error(logger, code, "bulk.drive", e, event_id=bulk_run_id)
        def fail(run):
            # Attribute the fault to the folder that was in flight, so the
            # summary points at the folder that caused it.
            current = run.get("current_folder")
            for folder in run.get("folders", []):
                if folder.get("source_folder") == current and (folder.get("status") == FOLDER_RUNNING or (folder.get("status") == FOLDER_PENDING and not folder.get("batch_name"))):
                    folder["status"] = FOLDER_FAILED
                    folder["completed_at"] = _now()
                    folder["error"] = error_message
            run = _reconcile_counts(run)
            run.update(
                status=STATUS_FAILED,
                error_code=code,
                completed_at=_now(),
                error=((f"{error_message} {run['error']}" if run.get("checkpoint_error") else (f"Folder {current!r}: {error_message}" if current else error_message))),
                current_batch_id=None,
            )
        await _call(bulk_manager.mutate, bulk_run_id, fail, with_batches=True)
        _emit_progress(bulk_run_id)
    finally:
        try:
            await _call(bulk_manager.release_run_lock, bulk_run_id)
        finally:
            _tasks.pop(bulk_run_id, None)
            _cancel_targets.pop(bulk_run_id, None)


async def _drive_folders(bulk_run_id: str) -> None:
    run = bulk_manager.get_run(bulk_run_id)
    if run is None:
        raise LookupError(bulk_run_id)

    _validate_run_preconditions(run)

    for index, folder in enumerate(run.get("folders", [])):
        # Re-read: pause/cancel and per-folder updates are written by others.
        run = bulk_manager.get_run(bulk_run_id) or run
        folder = run["folders"][index]
        source_folder = folder["source_folder"]

        if run.get("cancel_requested"):
            return await _call(_finalise, bulk_run_id, STATUS_CANCELLED)
        if run.get("pause_requested"):
            return await _call(_finalise, bulk_run_id, STATUS_PAUSED)
        if folder.get("status") in FOLDER_DONE_STATUSES:
            # Already done in an earlier attempt — never re-processed.
            logger.info("Bulk run %s: skipping completed folder %s", bulk_run_id, source_folder)
            continue

        await _process_folder(bulk_run_id, index)

        run = bulk_manager.get_run(bulk_run_id) or run
        folder = run["folders"][index]
        if folder.get("status") == FOLDER_FAILED and not settings.BULK_CONTINUE_ON_BATCH_ERROR:
            return await _call(_finalise,
                bulk_run_id,
                STATUS_FAILED,
                error=f"Folder {source_folder!r} failed and "
                      "BULK_CONTINUE_ON_BATCH_ERROR is disabled",
            )
        # A stop requested mid-batch takes effect at this boundary.
        if run.get("cancel_requested"):
            return await _call(_finalise, bulk_run_id, STATUS_CANCELLED)
        if run.get("pause_requested"):
            return await _call(_finalise, bulk_run_id, STATUS_PAUSED)

    run = bulk_manager.get_run(bulk_run_id) or run
    has_problems = any(
        f.get("status") in (FOLDER_FAILED, FOLDER_COMPLETED_WITH_ERRORS)
        for f in run.get("folders", [])
    )
    await _call(_finalise,
        bulk_run_id,
        STATUS_COMPLETED_WITH_ERRORS if has_problems else STATUS_COMPLETED,
    )


def _validate_run_preconditions(run: Dict[str, Any]) -> None:
    """Structural checks that must hold before any folder is processed."""
    if not run.get("schema_fields"):
        raise StructuralError("The run has an empty field list", code="empty_fields")
    if not bulk_import.is_enabled():
        raise StructuralError("BULK_IMPORT_ROOT is not configured or unreachable", code="import_unavailable")
    template_id = run.get("template_id")
    if template_id and template_service.get_template(template_id) is None:
        # The frozen schema_fields still describe the run, but a vanished
        # template means the operator's configuration no longer exists.
        raise StructuralError("Template no longer exists", code="template_missing")


async def _drain_progress(progress_tasks) -> None:
    """Join submitted progress even if cancellation lands at drain entry.

    No child drain task is created: gather registration is synchronous, and
    both the initial scheduling checkpoint and every join await are protected.
    The OCR writer has already been joined, so it can submit no more callbacks.
    """
    cancelled = False
    try:
        await asyncio.sleep(0)
    except asyncio.CancelledError:
        cancelled = True
    pending = asyncio.gather(*tuple(progress_tasks), return_exceptions=True)
    while not pending.done():
        try:
            await asyncio.shield(pending)
        except asyncio.CancelledError:
            cancelled = True
    pending.result()  # Retrieve every outcome, including callback exceptions.
    if cancelled:
        raise asyncio.CancelledError()


async def _process_folder(bulk_run_id: str, index: int) -> None:
    """Materialise (if needed) and process exactly one folder."""
    run = bulk_manager.get_run(bulk_run_id)
    assert run is not None
    folder = run["folders"][index]
    source_folder = folder["source_folder"]
    batch_name = folder.get("batch_name")

    # Claim the folder first, so a failure during import is attributed to it
    # and the progress view shows what is being worked on.
    await _call(bulk_manager.update_folder,
        bulk_run_id, source_folder, status=FOLDER_PENDING, started_at=_now(), error=None
    )
    await _call(bulk_manager.update_run,
        bulk_run_id, current_folder=source_folder, current_batch_id=batch_name
    )
    _emit_progress(bulk_run_id)

    # ---------------------------------------------------------------- register
    if not batch_name:
        try:
            from app.api.api_v1.endpoints.batches import _joined_calculation
            materialised = {}
            def materialise():
                imported = bulk_import.materialise_folder(
                    source_folder,
                    fields=run["schema_fields"],
                    prompt_template=run.get("prompt_template"),
                    field_rules=run.get("field_rules"),
                    authority_bindings=run.get("authority_bindings"),
                    field_groups=run.get("field_groups"),
                    describe_pictures=bool(run.get("describe_pictures")),
                )
                materialised.update(imported)
                return imported
            try:
                imported = await _joined_calculation(materialise)
            except asyncio.CancelledError:
                # The joined import may have committed History. Keep its batch
                # association even on cancellation, updating bulk state on-loop.
                if materialised:
                    await _call(bulk_manager.update_folder,
                        bulk_run_id, source_folder, batch_name=materialised["batch_name"],
                        images_total=materialised["images_total"],
                    )
                raise
        except bulk_import.BulkImportError as e:
            # A selected folder that cannot be read is a configuration fault
            # that will apply to the rest of the run too.
            raise StructuralError("Cannot import source folder", code="import_failed") from e
        batch_name = imported["batch_name"]
        await _call(bulk_manager.update_folder,
            bulk_run_id, source_folder, batch_name=batch_name,
            images_total=imported["images_total"],
        )

    await _call(bulk_manager.update_run, bulk_run_id, current_batch_id=batch_name)

    # ----------------------------------------------------------------- process
    owned = False
    def reserve(current):
        nonlocal owned
        if current["status"] != STATUS_RUNNING or current.get("pause_requested") or current.get("cancel_requested"):
            return False
        folder = current["folders"][index]
        if folder["source_folder"] != source_folder or folder.get("batch_name") != batch_name:
            raise BulkRevisionConflict()
        owned = batch_manager.acquire_batch_lock(batch_name)
        if owned:
            event = ws_manager.get_or_create_cancel_event(batch_name)
            event.clear()
            _cancel_targets[bulk_run_id] = (batch_name, event)
            current["folders"][index]["status"] = FOLDER_RUNNING
        return owned
    try:
        try:
            _, acquired = await bulk_manager.mutate_async(bulk_run_id, reserve, batch_names=[batch_name])
        except BaseException as exc:
            if isinstance(exc, TransactionTimeout):
                raise ReservationTimeout() from None
            if isinstance(exc, BatchMissingError):
                raise StructuralError("Batch is missing", code="batch_missing") from None
            raise

        # Reservation now yields to the event loop. Honor a stop requested while
        # the gate was queued, before run_ocr_task creates its cancellation event.
        # Deliver a pending task cancellation while Bulk still owns cleanup.
        await asyncio.sleep(0)
        latest = bulk_manager.get_run(bulk_run_id) or run
        if latest.get("pause_requested") or latest.get("cancel_requested"):
            await _call(bulk_manager.update_folder, bulk_run_id, source_folder, status=FOLDER_PENDING)
            _emit_progress(bulk_run_id)
            return

        if not acquired:
            await _call(bulk_manager.update_folder, bulk_run_id, source_folder, status=FOLDER_PENDING)
            raise ReservationBusy()

        # Seed the in-flight failure counter from disk so a resumed folder does not
        # forget failures recorded before the interruption.
        _, seed_failed = _folder_counts_from_checkpoint(batch_name)
        live: Dict[str, Any] = {"failed": seed_failed, "provider_fault": False}

        progress_tasks = set()
        async def handle_progress(name, progress):
            last = getattr(progress, "last_result", None)
            if last is not None and getattr(last, "success", True) is False:
                live["failed"] += 1
                if not live["provider_fault"] and _provider_fault(getattr(last, "error", None)):
                    # A credential or billing refusal will reject every remaining
                    # card too. Stop the in-flight batch now, using the same
                    # cooperative event a pause uses: process_batch checks it after
                    # the current image, once that checkpoint has been written, so
                    # nothing already extracted is lost. _classify_folder then sees
                    # the recorded fault and raises StructuralError to stop the run.
                    live["provider_fault"] = True
                    logger.error(
                        "Bulk run %s: provider refused the request while processing %s — "
                        "stopping the folder instead of sending the remaining cards",
                        bulk_run_id, source_folder,
                    )
                    target = _cancel_targets.get(bulk_run_id)
                    if target is not None:
                        target[1].set()
            count = int(getattr(progress, "current", 0))
            failed_count = live["failed"]
            def update(current):
                folder = current["folders"][index]
                if current["status"] != STATUS_RUNNING or folder["status"] != FOLDER_RUNNING or folder.get("batch_name") != batch_name:
                    return False
                if count < folder.get("images_processed", 0):
                    return False
                folder["images_processed"] = count
                folder["images_failed"] = max(folder.get("images_failed", 0), min(count, failed_count))
                if last is not None:
                    current["last_image"] = getattr(last, "filename", None)
                return True
            _, accepted = await bulk_manager.mutate_async(bulk_run_id, update)
            if accepted:
                current_state = ws_manager.batch_states.get(name)
                if getattr(current_state, "status", None) not in {"completed", "cancelled", "failed"}:
                    await ws_manager.broadcast_progress(name, progress)
                _emit_progress(bulk_run_id)

        async def on_progress(name, progress):
            task = asyncio.current_task()
            progress_tasks.add(task)
            try:
                await handle_progress(name, progress)
            except Exception as exc:
                live["error"] = exc
                report_error(logger, "bulk_progress_failed", "bulk.progress", exc, event_id=bulk_run_id)
                target = _cancel_targets.get(bulk_run_id)
                if target is not None:
                    target[1].set()
            finally:
                progress_tasks.discard(task)

        # Deferred import: batches.py imports service modules, so importing it at
        # module scope here would create a cycle.
        from app.api.api_v1.endpoints.batches import run_ocr_task

        # run_ocr_task owns the lifecycle of this batch, including releasing the
        # batch lock in its finally block. It never raises — it records a failed
        # batch instead — so the outcome is read back from disk and from the final
        # broadcast state below.
        # The provider and model frozen in run.json are authoritative: a bulk batch
        # carries no provider in its own config.json, and passing them explicitly is
        # what keeps an "ollama" run off a paid remote endpoint. The live template is
        # deliberately not consulted here.
        # A previous attempt's terminal cache is not this attempt's terminal state.
        # Clear it only at the actual handoff, after the post-reservation stop check.
        ws_manager.batch_states.pop(batch_name, None)
        def handoff():
            nonlocal owned
            # Called only after OCR has entered its own try/finally. From here
            # only that lifecycle may release the reservation.
            owned = False

        try:
            await run_ocr_task(
                batch_name,
                resume=True,
                progress_callback=on_progress,
                provider=run.get("provider"),
                model=run.get("model"),
                preserve_cancel_event=True,
                lock_handoff=handoff,
            )

        finally:
            await _drain_progress(progress_tasks)
        if live.get("error") is not None:
            if isinstance(live["error"], BulkStateError):
                raise live["error"] from None
            raise BulkStateError() from None

        # ---------------------------------------------------------------- classify
        await _call(_classify_folder, bulk_run_id, index, batch_name)
    finally:
        if owned:
            # Covers every exit after acquisition, including failures while
            # returning from the reservation commit or reading fresh metadata.
            _cancel_targets.pop(bulk_run_id, None)
            try:
                ws_manager.clear_cancel_event(batch_name)
            finally:
                batch_manager.release_batch_lock(batch_name)


def _classify_folder(bulk_run_id: str, index: int, batch_name: str) -> None:
    """Record a folder's outcome from its checkpoint and the batch's final state."""
    def classify(run):
        folder = run["folders"][index]
        source_folder = folder["source_folder"]

        stopped = bool(run.get("pause_requested") or run.get("cancel_requested"))

        try:
            checkpoint = batch_manager.get_batch_path(batch_name) / "checkpoint.json"
            results, _ = read_checkpoint(checkpoint) if checkpoint.exists() else ([], [])
        except Exception as e:
            raise StructuralError(
                "Could not read folder results", code="checkpoint_failed"
            ) from e

        succeeded = len(completed_filenames(results))
        failed_rows = [r for r in results if r.get("success") is not True]

        # An unexpected exception inside run_ocr_task surfaces as a "failed" batch.
        final_state = ws_manager.batch_states.get(batch_name)
        batch_status = getattr(final_state, "status", None)

        if getattr(ws_manager.batch_states.get(batch_name), "status", None) == "failed":
            raise StructuralError("Processing folder failed", code="batch_failed")
        if stopped:
            # Stopped on purpose: keep every completed result and leave the folder
            # pending so a Resume finishes it without re-sending completed images.
            folder.update(
                status=FOLDER_PENDING,
                images_processed=succeeded + len(failed_rows),
                images_failed=len(failed_rows),
            )
            return

        if batch_status == "failed":
            logger.error("Bulk run %s: batch %s reported failure", bulk_run_id, batch_name)
            raise StructuralError(
                "Processing folder failed", code="batch_failed"
            )

        provider_fault = next(
            (r.get("error") for r in failed_rows if _provider_fault(r.get("error"))),
            None,
        )
        if provider_fault:
            # Provider messages may echo OCR data: log only the failure category.
            logger.error(
                "Bulk run %s: provider refused the request while processing %s (credential or billing)",
                bulk_run_id, source_folder,
            )
            raise StructuralError(
                f"Provider refused the request while processing folder {source_folder!r} "
                "(credential or billing)", code="provider_refused"
            )

        if succeeded == 0:
            raise StructuralError(
                f"Folder {source_folder!r} produced no successful extractions — "
                "treating this as a configuration fault", code="no_extractions"
            )

        folder.update(
            status=FOLDER_COMPLETED_WITH_ERRORS if failed_rows else FOLDER_COMPLETED,
            images_processed=succeeded + len(failed_rows),
            images_failed=len(failed_rows),
            completed_at=_now(),
            error=None,
        )

    bulk_manager.mutate(bulk_run_id, classify, with_batches=True)
    _emit_progress(bulk_run_id)


def _finalise(bulk_run_id: str, status: str, error: Optional[str] = None, *, preserve_stop: bool = False, checkpoint_gate: bool = True) -> None:
    """Write a terminal (or paused) status with reconciled counters."""
    def finish(run):
        nonlocal status, error
        if checkpoint_gate:
            _reconcile_counts(run)
        else:
            # No OCR was admitted. An atomic checkpoint snapshot can establish
            # corruption, but cannot supply reconciled counters without the
            # Batch gate. Never overwrite counters from this fallback read.
            for folder in run.get("folders", []):
                if bulk_manager.folder_integrity_error(folder):
                    continue
                try:
                    _folder_counts_from_checkpoint(folder.get("batch_name"), required=_checkpoint_required(folder))
                except CheckpointError as exc:
                    report_error(logger, exc.code, "bulk.reserve.integrity", exc, event_id=bulk_run_id)
                    folder["integrity_error"] = exc.code
            bulk_manager.apply_integrity_state(run)
        if run.get("checkpoint_error"):
            status, error = STATUS_FAILED, run["error"]
        elif status != STATUS_FAILED:
            if run.get("cancel_requested"):
                status = STATUS_CANCELLED
            elif run.get("pause_requested"):
                status = STATUS_PAUSED
        run.update(status=status, error=error, current_batch_id=None)
        if status != STATUS_PAUSED:
            run.update(completed_at=_now(), current_folder=None)
    run = bulk_manager.mutate(bulk_run_id, finish, with_batches=checkpoint_gate)
    if run is None:
        return
    if status in TERMINAL_STATUSES:
        # No request context here (the orchestrator outlives the request that
        # started it), so the actor is the service account. Counts and status
        # only — never extracted metadata.
        log_event(
            "bulk_run_completed",
            result="failure" if status == STATUS_FAILED else "success",
            target=bulk_run_id,
            run_name=run.get("name"),
            final_status=status,
            folders=run.get("folders_total"),
            folders_completed=run.get("folders_completed"),
            images_processed=run.get("images_processed"),
            images_failed=run.get("images_failed"),
            provider=run.get("provider"),
            provider_host=_provider_host(run.get("provider")),
        )
    _emit_progress(bulk_run_id)


def _refresh_and_emit(bulk_run_id: str) -> None:
    bulk_manager.mutate(bulk_run_id, _reconcile_counts, with_batches=True)
    _emit_progress(bulk_run_id)


def _emit_progress(bulk_run_id: str) -> None:
    """Publish the run's current state to its WebSocket channel (Phase 6)."""
    from app.services.bulk_progress import publish_bulk_progress

    publish_bulk_progress(bulk_run_id)
