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

from app.core.audit import log_event
from app.core.checkpoint import completed_filenames, read_checkpoint
from app.core.config import settings
from app.services import bulk_import
from app.services.batch_manager import BatchMissingError, batch_manager
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


class StructuralError(Exception):
    """A fault that would invalidate every following folder — stop the run."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_detail(detail: str, limit: int = 200) -> str:
    """Bound an error string before it is stored in run.json or shown in the UI.

    Provider and engine messages can embed a slice of the model's response, and
    run.json must stay free of extracted metadata and small enough to rewrite
    after every image. The full message is always logged.
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
def _folder_counts_from_checkpoint(batch_name: Optional[str]) -> Tuple[int, int]:
    """(processed, failed) for a batch, derived from its own checkpoint.

    Authoritative and idempotent: derived from disk rather than incremented, so
    resuming a run cannot double-count images it already tallied.
    """
    if not batch_name:
        return 0, 0
    try:
        checkpoint = batch_manager.get_batch_path(batch_name) / "checkpoint.json"
    except ValueError:
        return 0, 0
    if not checkpoint.exists():
        return 0, 0
    try:
        results, _ = read_checkpoint(checkpoint)
    except Exception:
        logger.warning("Could not read checkpoint for %s while counting", batch_name)
        return 0, 0
    succeeded = len(completed_filenames(results))
    failed = sum(1 for r in results if r.get("success") is not True)
    return succeeded + failed, failed


def _reconcile_counts(run: Dict[str, Any]) -> Dict[str, Any]:
    """Refresh every folder's counters from its batch checkpoint, then the run's.

    Called before starting or resuming, so the numbers an operator sees always
    match what is actually on disk.
    """
    for folder in run.get("folders", []):
        processed, failed = _folder_counts_from_checkpoint(folder.get("batch_name"))
        if folder.get("batch_name"):
            folder["images_processed"] = processed
            folder["images_failed"] = failed
    return bulk_manager.recount_progress(run)


# --------------------------------------------------------------------------- #
# Public controls
# --------------------------------------------------------------------------- #
async def start_run(bulk_run_id: str) -> Dict[str, Any]:
    """Start or resume a run. Claims the single-run lock and spawns the driver.

    Raises ``RuntimeError`` when another run holds the lock or this run is
    already executing, and ``LookupError`` when the run does not exist.
    """
    run = bulk_manager.get_run(bulk_run_id)
    if run is None:
        raise LookupError(bulk_run_id)
    if is_task_active(bulk_run_id):
        raise RuntimeError("This bulk run is already processing")
    if not bulk_manager.acquire_run_lock(bulk_run_id):
        holder = bulk_manager.locked_run_id()
        if holder == bulk_run_id:
            # Our own stale lock from a crashed process — mark_interrupted_runs
            # normally clears it at startup; be tolerant if it did not.
            bulk_manager.release_run_lock()
            bulk_manager.acquire_run_lock(bulk_run_id)
        else:
            raise RuntimeError("Another bulk run is already in progress")

    run = _reconcile_counts(run)
    run.update(
        status=STATUS_RUNNING,
        started_at=run.get("started_at") or _now(),
        interrupted_at=None,
        completed_at=None,
        error=None,
        pause_requested=False,
        cancel_requested=False,
    )
    bulk_manager.save_run(run)

    _tasks[bulk_run_id] = asyncio.create_task(_drive(bulk_run_id))
    return run


def request_pause(bulk_run_id: str) -> bool:
    """Ask the run to stop after the current image. Returns False if unknown."""
    return _request_stop(bulk_run_id, pause=True)


def request_cancel(bulk_run_id: str) -> bool:
    """Ask the run to cancel after the current image. Returns False if unknown."""
    return _request_stop(bulk_run_id, pause=False)


def _request_stop(bulk_run_id: str, *, pause: bool) -> bool:
    run = bulk_manager.get_run(bulk_run_id)
    if run is None:
        return False
    field = "pause_requested" if pause else "cancel_requested"
    run = bulk_manager.update_run(bulk_run_id, **{field: True}) or run
    # Cooperative stop of the in-flight batch: process_batch checks the event
    # after each image, once that image's checkpoint has been written, and the
    # engine checks it again before any retry, so no further request goes out.
    current_batch = run.get("current_batch_id")
    if current_batch:
        ws_manager.cancel_batch(current_batch)
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
    except asyncio.CancelledError:
        # The process is going down. Leave the run as "running" so the startup
        # hook marks it interrupted and a human decides whether to resume (D2).
        logger.warning("Bulk run %s cancelled by the event loop", bulk_run_id)
        raise
    except Exception as e:
        logger.exception("Bulk run %s failed", bulk_run_id)
        run = bulk_manager.get_run(bulk_run_id)
        if run is not None:
            # Attribute the fault to the folder that was in flight, so the
            # summary points at the folder that caused it.
            current = run.get("current_folder")
            for folder in run.get("folders", []):
                if folder.get("source_folder") == current and folder.get("status") == FOLDER_RUNNING:
                    folder["status"] = FOLDER_FAILED
                    folder["completed_at"] = _now()
                    folder["error"] = str(e)
            run = _reconcile_counts(run)
            run.update(
                status=STATUS_FAILED,
                completed_at=_now(),
                error=str(e),
                current_batch_id=None,
                pause_requested=False,
                cancel_requested=False,
            )
            bulk_manager.save_run(run)
        _emit_progress(bulk_run_id)
    finally:
        bulk_manager.release_run_lock()
        _tasks.pop(bulk_run_id, None)


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
            return _finalise(bulk_run_id, STATUS_CANCELLED)
        if run.get("pause_requested"):
            return _finalise(bulk_run_id, STATUS_PAUSED)
        if folder.get("status") in FOLDER_DONE_STATUSES:
            # Already done in an earlier attempt — never re-processed.
            logger.info("Bulk run %s: skipping completed folder %s", bulk_run_id, source_folder)
            continue

        await _process_folder(bulk_run_id, index)

        run = bulk_manager.get_run(bulk_run_id) or run
        folder = run["folders"][index]
        if folder.get("status") == FOLDER_FAILED and not settings.BULK_CONTINUE_ON_BATCH_ERROR:
            return _finalise(
                bulk_run_id,
                STATUS_FAILED,
                error=f"Folder {source_folder!r} failed and "
                      "BULK_CONTINUE_ON_BATCH_ERROR is disabled",
            )
        # A stop requested mid-batch takes effect at this boundary.
        if run.get("cancel_requested"):
            return _finalise(bulk_run_id, STATUS_CANCELLED)
        if run.get("pause_requested"):
            return _finalise(bulk_run_id, STATUS_PAUSED)

    run = bulk_manager.get_run(bulk_run_id) or run
    has_problems = any(
        f.get("status") in (FOLDER_FAILED, FOLDER_COMPLETED_WITH_ERRORS)
        for f in run.get("folders", [])
    )
    _finalise(
        bulk_run_id,
        STATUS_COMPLETED_WITH_ERRORS if has_problems else STATUS_COMPLETED,
    )


def _validate_run_preconditions(run: Dict[str, Any]) -> None:
    """Structural checks that must hold before any folder is processed."""
    if not run.get("schema_fields"):
        raise StructuralError("The run has an empty field list")
    if not bulk_import.is_enabled():
        raise StructuralError("BULK_IMPORT_ROOT is not configured or unreachable")
    template_id = run.get("template_id")
    if template_id and template_service.get_template(template_id) is None:
        # The frozen schema_fields still describe the run, but a vanished
        # template means the operator's configuration no longer exists.
        raise StructuralError(f"Template {template_id!r} no longer exists")


async def _process_folder(bulk_run_id: str, index: int) -> None:
    """Materialise (if needed) and process exactly one folder."""
    run = bulk_manager.get_run(bulk_run_id)
    assert run is not None
    folder = run["folders"][index]
    source_folder = folder["source_folder"]
    batch_name = folder.get("batch_name")

    # Claim the folder first, so a failure during import is attributed to it
    # and the progress view shows what is being worked on.
    bulk_manager.update_folder(
        bulk_run_id, source_folder, status=FOLDER_RUNNING, started_at=_now(), error=None
    )
    bulk_manager.update_run(
        bulk_run_id, current_folder=source_folder, current_batch_id=batch_name
    )
    _emit_progress(bulk_run_id)

    # ---------------------------------------------------------------- register
    if not batch_name:
        try:
            imported = bulk_import.materialise_folder(
                source_folder,
                fields=run["schema_fields"],
                prompt_template=run.get("prompt_template"),
                field_rules=run.get("field_rules"),
                authority_bindings=run.get("authority_bindings"),
                field_groups=run.get("field_groups"),
                describe_pictures=bool(run.get("describe_pictures")),
            )
        except bulk_import.BulkImportError as e:
            # A selected folder that cannot be read is a configuration fault
            # that will apply to the rest of the run too.
            raise StructuralError(f"Cannot import folder {source_folder!r}: {e}") from e
        batch_name = imported["batch_name"]
        bulk_manager.update_folder(
            bulk_run_id,
            source_folder,
            batch_name=batch_name,
            images_total=imported["images_total"],
        )

    bulk_manager.update_run(bulk_run_id, current_batch_id=batch_name)

    # ----------------------------------------------------------------- process
    try:
        acquired = batch_manager.acquire_batch_lock(batch_name)
    except BatchMissingError as e:
        # The batch this folder was materialised into has been deleted or
        # purged. Nothing here can recover it, and the operator has to re-import
        # the folder, so the run stops with a message that says exactly that
        # rather than a raw errno on the lockfile path.
        raise StructuralError(str(e)) from e

    if not acquired:
        # The bulk single-run lock rules out a second bulk run, so this is a
        # manual retry or a stale lock. Folder-level, not structural.
        bulk_manager.update_folder(
            bulk_run_id,
            source_folder,
            status=FOLDER_FAILED,
            completed_at=_now(),
            error="A run is already in progress for this batch",
        )
        _refresh_and_emit(bulk_run_id)
        return

    # Seed the in-flight failure counter from disk so a resumed folder does not
    # forget failures recorded before the interruption.
    _, seed_failed = _folder_counts_from_checkpoint(batch_name)
    live: Dict[str, Any] = {"failed": seed_failed, "provider_fault": False}

    async def on_progress(name: str, progress: Any) -> None:
        # Keep the per-batch progress view working exactly as before...
        await ws_manager.broadcast_progress(name, progress)
        # ...and fold the same event into the bulk counters.
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
                ws_manager.cancel_batch(name)
        bulk_manager.update_folder(
            bulk_run_id,
            source_folder,
            images_processed=getattr(progress, "current", 0),
            images_failed=live["failed"],
        )
        if last is not None:
            bulk_manager.update_run(bulk_run_id, last_image=getattr(last, "filename", None))
        _emit_progress(bulk_run_id)

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
    await run_ocr_task(
        batch_name,
        resume=True,
        progress_callback=on_progress,
        provider=run.get("provider"),
        model=run.get("model"),
    )

    # ---------------------------------------------------------------- classify
    _classify_folder(bulk_run_id, index, batch_name)


def _classify_folder(bulk_run_id: str, index: int, batch_name: str) -> None:
    """Record a folder's outcome from its checkpoint and the batch's final state."""
    run = bulk_manager.get_run(bulk_run_id)
    assert run is not None
    folder = run["folders"][index]
    source_folder = folder["source_folder"]

    stopped = bool(run.get("pause_requested") or run.get("cancel_requested"))

    try:
        checkpoint = batch_manager.get_batch_path(batch_name) / "checkpoint.json"
        results, _ = read_checkpoint(checkpoint) if checkpoint.exists() else ([], [])
    except Exception as e:
        raise StructuralError(
            f"Could not read results for folder {source_folder!r}: {e}"
        ) from e

    succeeded = len(completed_filenames(results))
    failed_rows = [r for r in results if r.get("success") is not True]

    # An unexpected exception inside run_ocr_task surfaces as a "failed" batch.
    final_state = ws_manager.batch_states.get(batch_name)
    batch_status = getattr(final_state, "status", None)

    if stopped:
        # Stopped on purpose: keep every completed result and leave the folder
        # pending so a Resume finishes it without re-sending completed images.
        bulk_manager.update_folder(
            bulk_run_id,
            source_folder,
            status=FOLDER_PENDING,
            images_processed=succeeded + len(failed_rows),
            images_failed=len(failed_rows),
        )
        _refresh_and_emit(bulk_run_id)
        return

    if batch_status == "failed":
        detail = getattr(final_state, "error", None) or "unknown error"
        logger.error("Bulk run %s: batch %s reported failure: %s", bulk_run_id, batch_name, detail)
        raise StructuralError(
            f"Processing folder {source_folder!r} failed: {_safe_detail(detail)}"
        )

    provider_fault = next(
        (r.get("error") for r in failed_rows if _provider_fault(r.get("error"))),
        None,
    )
    if provider_fault:
        # The provider error goes to the application log, not into run.json: a
        # provider message can echo part of the model's response, and run.json is
        # documented as carrying no extracted metadata. The operator needs the
        # backend log to fix a credential or a balance anyway.
        logger.error(
            "Bulk run %s: provider refused the request while processing %s: %s",
            bulk_run_id, source_folder, provider_fault,
        )
        raise StructuralError(
            f"Provider refused the request while processing folder {source_folder!r} "
            "(credential or billing) — see the backend log for the provider's message"
        )

    if succeeded == 0:
        raise StructuralError(
            f"Folder {source_folder!r} produced no successful extractions — "
            "treating this as a configuration fault"
        )

    bulk_manager.update_folder(
        bulk_run_id,
        source_folder,
        status=FOLDER_COMPLETED_WITH_ERRORS if failed_rows else FOLDER_COMPLETED,
        images_processed=succeeded + len(failed_rows),
        images_failed=len(failed_rows),
        completed_at=_now(),
        error=None,
    )
    _refresh_and_emit(bulk_run_id)


def _finalise(bulk_run_id: str, status: str, error: Optional[str] = None) -> None:
    """Write a terminal (or paused) status with reconciled counters."""
    run = bulk_manager.get_run(bulk_run_id)
    if run is None:
        return
    run = _reconcile_counts(run)
    run["status"] = status
    run["error"] = error
    run["pause_requested"] = False
    run["cancel_requested"] = False
    run["current_batch_id"] = None
    if status not in (STATUS_PAUSED,):
        run["completed_at"] = _now()
        run["current_folder"] = None
    bulk_manager.save_run(run)

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
    run = bulk_manager.get_run(bulk_run_id)
    if run is not None:
        bulk_manager.save_run(bulk_manager.recount_progress(run))
    _emit_progress(bulk_run_id)


def _emit_progress(bulk_run_id: str) -> None:
    """Publish the run's current state to its WebSocket channel (Phase 6)."""
    from app.services.bulk_progress import publish_bulk_progress

    publish_bulk_progress(bulk_run_id)
