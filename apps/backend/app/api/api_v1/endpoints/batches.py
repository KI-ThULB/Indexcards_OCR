from app.core.checkpoint import read_checkpoint_snapshot
from urllib.parse import urlparse
from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends, Request
from fastapi.responses import Response
from typing import Any, Callable, Dict, List, Optional
import json
import asyncio
import contextvars
import hashlib
import logging

from app.services.batch_manager import batch_manager
from app.services.ocr_engine import ocr_engine
from app.services.ws_manager import ws_manager
from pathlib import Path
from app.models.schemas import BatchCreate, BatchHistoryItem, BatchProgress, BatchResponse, BatchStartRequest, ExportEvent, ResultPatch
from app.core.config import settings, get_settings, Settings
from app.core.transactions import TransactionError, TransactionTimeout
from app.core.rate_limit import limiter
from app.core.error_reporting import report_error
from app.core.security import validate_batch_name, validate_filename
# Checkpoint I/O lives in one place so the engine and this API can never disagree on
# the on-disk format again (the old local read_checkpoint migrated legacy files on
# read, which broke resume/retry for any batch whose results had been viewed).
# Re-exported here because the existing call sites below use these bare names.
from app.core.checkpoint import CheckpointError, read_checkpoint, write_checkpoint
from app.core.images import iter_image_files
from app.core.audit import log_event
from app.services.validation import groups as group_util

logger = logging.getLogger(__name__)

router = APIRouter()


def _ensure_batch_name(batch_name: str) -> str:
    """Validate a user-supplied batch name at the endpoint boundary, 400 on failure (K-3)."""
    try:
        return validate_batch_name(batch_name)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid batch name")


def _ensure_filename(filename: str) -> str:
    """Validate a user-supplied filename at the endpoint boundary, 400 on failure (K-3)."""
    try:
        return validate_filename(filename)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid filename")


def _assert_mutable(batch_path: Path) -> None:
    _ensure_no_retry_recovery(batch_path.name)
    if (batch_path / ".run.lock").exists():
        raise HTTPException(status_code=409, detail="Batch is processing (batch_processing_active); curator changes are not allowed")


async def _batch_http(batch_path: Path, operation: Callable[[], Any]):
    try:
        return await batch_manager.run_batch_async(batch_path, operation)
    except TransactionError as exc:
        identifier = report_error(logger, exc.code, "batch.transaction", exc)
        raise HTTPException(status_code=409 if isinstance(exc, TransactionTimeout) else 500,
                            detail=f"Batch transaction unavailable ({exc.code}). Reference: {identifier}") from None


async def _prepare_http(batch_path: Path, operation: Callable[[Dict[str, bool]], Any]):
    reservation = {"owned": False}
    try:
        return await _batch_http(batch_path, lambda: operation(reservation))
    except BaseException:
        # SAR-04a has joined the preparation callback; no OCR has been scheduled.
        if reservation["owned"]:
            batch_manager.release_batch_lock(batch_path.name)
        raise


async def _joined_calculation(operation: Callable[[], Any]):
    """No gate held: join revalidation/provider work even on repeated cancel."""
    def work():
        try:
            return operation(), None
        except Exception as exc:
            return None, exc

    loop = asyncio.get_running_loop()
    context = contextvars.copy_context()
    future = loop.run_in_executor(None, context.run, work)
    try:
        value, error = await asyncio.shield(future)
    except asyncio.CancelledError:
        while not future.done():
            try:
                await asyncio.shield(future)
            except asyncio.CancelledError:
                continue
        _, error = future.result()
        if error is not None:
            raise error from None
        raise
    if error is not None:
        raise error from None
    return value


def _batch_field_groups(batch_dir: Path) -> Dict[str, Any]:
    """The batch's frozen repeatable-group definitions, or {} for a scalar batch."""
    config_path = batch_dir / "config.json"
    if not config_path.exists():
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except (OSError, ValueError):
        logger.warning("Could not read config.json for %s while patching", batch_dir.name)
        return {}
    groups = config.get("field_groups")
    return groups if isinstance(groups, dict) else {}


def _apply_group_patch(row: Dict[str, Any], patch: ResultPatch, definition: Any) -> None:
    """Apply one repeatable-group operation to a result row.

    The API is granular — it addresses a single child of a single entry — while
    the storage is the whole edited array under ``edited_data[group]``. That keeps
    ``edited_data`` a ``Dict[str, str]`` and means add/remove/reorder cannot leave
    orphaned per-child keys behind. Raises HTTPException(400) on a bad address; a
    caller's mistake must never silently corrupt a card.
    """
    group = patch.group or ""
    items = group_util.effective_items(row, group)
    op = patch.group_op
    limit = group_util.max_items(definition)

    if op == "add":
        if len(items) >= limit:
            raise HTTPException(
                status_code=400,
                detail=f"Group '{group}' already holds its maximum of {limit} entries",
            )
        blank = {name: "" for name in group_util.child_names(definition)}
        position = len(items) if patch.index is None else patch.index
        if not 0 <= position <= len(items):
            raise HTTPException(status_code=400, detail="Insert position out of range")
        items.insert(position, blank)
    elif op == "remove":
        if patch.index is None or not 0 <= patch.index < len(items):
            raise HTTPException(status_code=400, detail="Entry index out of range")
        items.pop(patch.index)
    elif op == "move":
        if patch.index is None or not 0 <= patch.index < len(items):
            raise HTTPException(status_code=400, detail="Entry index out of range")
        if patch.to_index is None or not 0 <= patch.to_index < len(items):
            raise HTTPException(status_code=400, detail="Target index out of range")
        items.insert(patch.to_index, items.pop(patch.index))
    elif op is None:
        # Value edit on one child of one entry.
        if not patch.field:
            raise HTTPException(status_code=400, detail="A group value patch requires 'field'")
        if patch.field not in group_util.child_names(definition):
            raise HTTPException(
                status_code=400, detail=f"Unknown child field '{patch.field}' in group '{group}'"
            )
        if patch.index is None or not 0 <= patch.index < len(items):
            raise HTTPException(status_code=400, detail="Entry index out of range")
        items[patch.index][patch.field] = patch.value or ""
    else:
        raise HTTPException(status_code=400, detail=f"Unknown group operation '{op}'")

    # Re-normalise so every entry carries exactly the defined children in order —
    # the canonical form the exporters rely on. Structural ops keep empty entries,
    # which normalise_group would otherwise drop, so they are written directly.
    names = group_util.child_names(definition)
    canonical = [{name: str(item.get(name, "") or "") for name in names} for item in items]
    if row.get("edited_data") is None:
        row["edited_data"] = {}
    row["edited_data"][group] = group_util.serialise_group(canonical)


class ProviderConfigurationError(RuntimeError):
    """No usable extraction provider was configured for a batch.

    Raised before any HTTP request is made, so a configuration gap can never be
    resolved by quietly picking a provider on the caller's behalf.
    """

    def __init__(self, message: str, *, code: str = "provider_invalid") -> None:
        super().__init__(message)
        self.code = code if code in {"provider_missing", "provider_unknown", "provider_disabled"} else "provider_invalid"


PROVIDER_OLLAMA = "ollama"
PROVIDER_OPENROUTER = "openrouter"
PROVIDER_GPUSTACK = "gpustack"
SUPPORTED_PROVIDERS = (PROVIDER_OLLAMA, PROVIDER_OPENROUTER, PROVIDER_GPUSTACK)


def _resolve_provider(provider: Optional[str], model: Optional[str] = None):
    """Returns (api_endpoint, model_name, api_key) for the given provider.

    Fails closed. This used to default to OpenRouter, which meant any caller
    that did not supply a provider silently sent card images to a paid,
    off-premise endpoint — the bulk orchestrator did exactly that. An absent or
    unknown provider is a configuration fault and is raised as one; it is never
    substituted, in either direction.
    """
    normalised = (provider or "").strip().lower()
    if normalised == PROVIDER_OLLAMA:
        return (
            settings.OLLAMA_API_ENDPOINT,
            model or settings.OLLAMA_MODEL_NAME,
            settings.OLLAMA_API_KEY,
        )
    if normalised == PROVIDER_OPENROUTER:
        return settings.API_ENDPOINT, model or settings.MODEL_NAME, settings.OPENROUTER_API_KEY
    if normalised == PROVIDER_GPUSTACK:
        if not settings.GPUSTACK_ENABLED:
            raise ProviderConfigurationError("GPUStack provider is disabled", code="provider_disabled")
        return (
            settings.GPUSTACK_API_ENDPOINT,
            model or settings.GPUSTACK_DEFAULT_MODEL,
            settings.GPUSTACK_API_KEY,
        )
    if not normalised:
        raise ProviderConfigurationError(
            "No extraction provider is configured for this batch. Start it with an "
            f"explicit provider ({' or '.join(SUPPORTED_PROVIDERS)}).", code="provider_missing"
        )
    raise ProviderConfigurationError(f"Unknown extraction provider: {provider!r}", code="provider_unknown")


def provider_endpoint_host(provider: Optional[str]) -> str:
    """Host the given provider resolves to, for the audit trail.

    Host only — never the full URL — so no path, query string or credential can
    reach the audit log. Empty string when the provider is not configured.
    """
    try:
        endpoint, _model, _key = _resolve_provider(provider)
    except ProviderConfigurationError:
        return ""
    return urlparse(endpoint).hostname or ""


async def run_ocr_task(
    batch_name: str,
    resume: bool = True,
    retry_errors: bool = False,
    progress_callback: Optional[Callable[[str, Any], Any]] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    preserve_cancel_event: bool = False,
    lock_handoff: Optional[Callable[[], None]] = None,
):
    """Background task to run OCR on a batch.

    *progress_callback* defaults to ``ws_manager.broadcast_progress`` — exactly
    the previous behaviour. The bulk orchestrator passes a wrapper that forwards
    per-batch progress AND updates its own run counters, so the per-batch and
    bulk progress views run off one event stream rather than two.

    *provider* / *model* override whatever the batch's ``config.json`` holds.
    The interactive path persists its choice into that file before scheduling
    this task and passes nothing here; the bulk orchestrator owns no batch
    config and passes the provider and model frozen in ``run.json`` instead.
    """
    release_run_lock = True
    on_progress = progress_callback or ws_manager.broadcast_progress
    # Get (or create) the cancel event and immediately clear it to ensure a fresh state.
    # This prevents a stale set event from a previous cancellation aborting the new run.
    try:
        # The Bulk caller retains cleanup responsibility until this lifecycle
        # has installed its finally block. No await splits ownership transfer.
        if lock_handoff is not None:
            lock_handoff()
        cancel_event = ws_manager.get_or_create_cancel_event(batch_name)
        if not preserve_cancel_event:
            cancel_event.clear()
        if batch_manager.retry_recovery_required(batch_name):
            raise RetryRecoveryRequired()
        batch_path = batch_manager.get_batch_path(batch_name)
        config_path = batch_path / "config.json"

        fields = None
        prompt_template = None
        config_provider = None
        config_model = None
        field_rules = None
        corrector_enabled = False
        corrector_cap = 100
        describe_pictures = False
        field_groups = None
        if config_path.exists():
            with open(config_path, "r") as f:
                config = json.load(f)
                fields = config.get("fields")
                prompt_template = config.get("prompt_template")
                config_provider = config.get("provider")
                config_model = config.get("model")
                field_rules = config.get("field_rules")
                corrector_enabled = config.get("corrector_enabled", False)
                corrector_cap = config.get("corrector_cap", 100)
                describe_pictures = config.get("describe_pictures", False)
                field_groups = config.get("field_groups")

        # When picture description is enabled, ensure the dedicated field is part of the
        # effective field list so the prompt asks for it and it appears as a column.
        if describe_pictures and fields is not None and ocr_engine.PICTURE_FIELD not in fields:
            fields = [*fields, ocr_engine.PICTURE_FIELD]

        # An explicit argument wins over the batch config, so the bulk run's
        # frozen provider cannot be overridden by whatever an earlier
        # interactive start happened to leave in config.json.
        effective_provider = provider or config_provider
        effective_model = model or config_model
        api_endpoint, model_name, api_key = _resolve_provider(effective_provider, effective_model)

        # If retry_errors is True, move files back from _errors so ocr_engine can process them.
        if retry_errors:
            error_dir = batch_path / "_errors"
            files = sorted(p for p in error_dir.iterdir() if p.is_file()) if error_dir.exists() else []
            await batch_manager.run_batch_async(batch_path, lambda: _prepare_retry_images(batch_path, files))

        await ocr_engine.process_batch(
            batch_dir=batch_path,
            fields=fields,
            progress_callback=on_progress,
            resume=resume,
            cancel_event=cancel_event,
            prompt_template=prompt_template,
            api_endpoint=api_endpoint,
            model_name=model_name,
            api_key=api_key,
            field_rules=field_rules,
            corrector_enabled=corrector_enabled,
            corrector_cap=corrector_cap,
            describe_pictures=describe_pictures,
            field_groups=field_groups,
        )

        # Completion decision: cooperative cancellation before this point wins.
        # Later requests cannot change the terminal outcome already being committed.
        final_status = "cancelled" if cancel_event.is_set() else "completed"
        await _joined_calculation(lambda: batch_manager.update_batch_status(batch_name, final_status))

        # Mark as completed (or cancelled) only after the history commit.
        last_state = ws_manager.batch_states.get(batch_name)
        if last_state:
            last_state.status = final_status
            await ws_manager.broadcast_progress(batch_name, last_state)
        else:
            # Edge case: no progress was ever broadcast — send completed/cancelled with zeroed progress
            final_state = BatchProgress(
                batch_name=batch_name,
                current=0,
                total=0,
                percentage=0.0,
                status=final_status,
            )
            await ws_manager.broadcast_progress(batch_name, final_state)


    except Exception as e:
        if isinstance(e, RetryRecoveryRequired):
            release_run_lock = False
        identifier = report_error(logger, e.code if isinstance(e, (ProviderConfigurationError, CheckpointError, TransactionError)) else "batch_processing_failed",
                     "batch.process", e)
        error_msg = (
            "Extraction provider configuration is invalid. Check the provider settings."
            if isinstance(e, ProviderConfigurationError)
            else "Batch processing failed. Please retry or contact the administrator."
        )
        if isinstance(e, CheckpointError):
            error_msg = f"Checkpoint could not be read or saved ({e.code}). Processing stopped."
        error_msg += f" Reference: {identifier}"
        last_state = ws_manager.batch_states.get(batch_name)
        if last_state:
            last_state.status = "failed"
            last_state.error = error_msg
        else:
            # No progress was ever broadcast — create minimal failed state
            last_state = BatchProgress(
                batch_name=batch_name,
                current=0,
                total=0,
                percentage=0.0,
                status="failed",
                error=error_msg,
            )
        if isinstance(e, CheckpointError):
            # Publish the known failure locally and persist it before any await:
            # repeated cancellation during socket delivery must not retain an
            # earlier completed status. Socket delivery remains best-effort.
            ws_manager.batch_states[batch_name] = last_state
            await _joined_calculation(lambda: batch_manager.update_batch_status(batch_name, "failed"))
        await ws_manager.broadcast_progress(batch_name, last_state)
        if not isinstance(e, CheckpointError):
            await _joined_calculation(lambda: batch_manager.update_batch_status(batch_name, "failed"))
    finally:
        # Clean up cancel event after the task ends (success, cancel, or failure)
        ws_manager.clear_cancel_event(batch_name)
        # Release the single-active-run lock so the batch can be started again (W-06)
        if release_run_lock:
            batch_manager.release_batch_lock(batch_name)


@router.post("/", response_model=BatchResponse)
def create_batch(batch_data: BatchCreate):
    """
    Creates a new batch from a list of files in a temporary session.
    Moves files from temp session to a permanent batch directory.
    Returns the generated batch name.
    """
    try:
        # Serialize nested FieldRule Pydantic models to plain dicts for JSON-safe storage
        fr = None
        if batch_data.field_rules:
            fr = {
                k: (v.dict() if hasattr(v, "dict") else v)
                for k, v in batch_data.field_rules.items()
            }

        # Serialize nested AuthorityBinding Pydantic models to plain dicts for JSON-safe storage
        ab = None
        if batch_data.authority_bindings:
            ab = {
                k: (v.dict() if hasattr(v, "dict") else v)
                for k, v in batch_data.authority_bindings.items()
            }

        # Serialise nested FieldGroup models to plain dicts, mirroring field_rules
        fg = None
        if batch_data.field_groups:
            fg = {
                k: (v.dict() if hasattr(v, "dict") else v)
                for k, v in batch_data.field_groups.items()
            }

        batch_name = batch_manager.create_batch(
            custom_name=batch_data.custom_name,
            session_id=batch_data.session_id,
            fields=batch_data.fields,
            prompt_template=batch_data.prompt_template,
            field_rules=fr,
            corrector_enabled=batch_data.corrector_enabled,
            corrector_cap=batch_data.corrector_cap,
            authority_bindings=ab,
            field_groups=fg,
            describe_pictures=batch_data.describe_pictures,
        )

        batch_path = batch_manager.get_batch_path(batch_name)
        files_count = len(iter_image_files(batch_path))

        return BatchResponse(
            batch_name=batch_name,
            status="uploaded",
            files_count=files_count
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Could not create batch. Check the upload session and batch configuration.")
    except TransactionError:
        raise
    except Exception as exc:
        # Return and log only a generic message (W-07/H-6).
        logger.error("Failed to create batch: exception_type=%s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Failed to create batch")


@router.get("/", response_model=List[str])
async def list_batches():
    """
    Lists all permanent batches.
    """
    return batch_manager.list_batches()


@router.get("/history", response_model=List[BatchHistoryItem])
def get_batch_history():
    """
    Returns full batch history with enriched metadata (file counts, error counts).
    Route placed before /{batch_name} routes to prevent FastAPI treating 'history' as a parameter.
    """
    return batch_manager.get_history()


@router.patch("/{batch_name}/results/{filename}", response_model=dict)
async def patch_result(batch_name: str, filename: str, patch: ResultPatch):
    _ensure_batch_name(batch_name)
    _ensure_filename(filename)
    return await _batch_http(batch_manager.get_batch_path(batch_name), lambda: _patch_result(batch_name, filename, patch))


def _patch_result(
    batch_name: str,
    filename: str,
    patch: ResultPatch,
):
    """
    Merge a single field edit and/or validation status update into checkpoint.json.
    Used by the Phase 9 Verify cockpit to persist curator edits durably.
    Single-curator use: O(N) read-modify-write is acceptable for batch sizes <= 500.
    Debounce calls from the frontend (300ms) to coalesce rapid edits.
    """
    _ensure_batch_name(batch_name)
    _ensure_filename(filename)
    batch_dir = batch_manager.get_batch_path(batch_name)
    _assert_mutable(batch_dir)
    checkpoint_path = batch_dir / "checkpoint.json"
    if not checkpoint_path.exists():
        raise HTTPException(status_code=404, detail="Checkpoint not found")
    # A scalar patch must still name a field. `field` is only optional on the
    # model so structural group operations need not send one.
    if patch.group is None and not patch.field:
        raise HTTPException(status_code=400, detail="'field' is required")

    field_groups = _batch_field_groups(batch_dir)
    if patch.group is not None and patch.group not in field_groups:
        raise HTTPException(status_code=400, detail=f"Unknown group '{patch.group}'")

    results, audit = read_checkpoint(checkpoint_path)
    # Find matching result row by filename
    found = False
    for row in results:
        if row.get("filename") == filename:
            if patch.group is not None:
                _apply_group_patch(row, patch, field_groups[patch.group])
                found = True
                break
            if patch.field and patch.value is not None:
                if "edited_data" not in row or row["edited_data"] is None:
                    row["edited_data"] = {}
                row["edited_data"][patch.field] = patch.value
            if patch.validation_status is not None and patch.field:
                if "validation" not in row or row["validation"] is None:
                    row["validation"] = {}
                if patch.field not in row["validation"]:
                    row["validation"][patch.field] = {}
                row["validation"][patch.field]["status"] = patch.validation_status
            # Reconciliation update uses clear_reconciliation: bool to avoid null-vs-omitted ambiguity.
            # Convention (version-independent, agreed between frontend and backend):
            #   clear_reconciliation=True → set reconciliation to null (clear it)
            #   reconciliation=<dict>     → set a new ReconciliationOutcome
            #   neither                   → leave reconciliation unchanged
            if patch.clear_reconciliation or patch.reconciliation is not None:
                if not row.get("validation"):
                    row["validation"] = {}
                if patch.field not in row["validation"]:
                    row["validation"][patch.field] = {}
                if patch.clear_reconciliation:
                    row["validation"][patch.field]["reconciliation"] = None
                else:
                    row["validation"][patch.field]["reconciliation"] = patch.reconciliation
            found = True
            break
    if not found:
        raise HTTPException(status_code=404, detail=f"Result {filename} not found in checkpoint")
    if patch.audit_entry is not None:
        audit.append(patch.audit_entry)
    write_checkpoint(checkpoint_path, results, audit)
    return {"ok": True}


@router.get("/{batch_name}/config", response_model=dict)
async def get_batch_config(batch_name: str):
    """
    Return batch config fields and field_rules for client-side validation re-run.
    Reads config.json (not checkpoint.json) — no migration needed.
    Used by CleanStep to get field_rules for post-transform revalidation.
    Route placed before /{batch_name} DELETE/generic routes to avoid path-parameter greedy matching.
    """
    _ensure_batch_name(batch_name)
    batch_dir = Path(settings.BATCHES_DIR) / batch_name
    config_path = batch_dir / "config.json"
    if not config_path.exists():
        raise HTTPException(status_code=404, detail="Batch config not found")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    return {
        "fields": config.get("fields", []),
        "field_rules": config.get("field_rules", None),
        "authority_bindings": config.get("authority_bindings", None),  # Phase 11
        "field_groups": config.get("field_groups", None),              # repeatable groups
    }


@router.delete("/{batch_name}/authority-cache", status_code=204)
async def delete_authority_cache(
    batch_name: str,
    dep_settings: Settings = Depends(get_settings),
):
    """Clear the per-batch authority reconciliation cache.
    Curator uses this when they believe authority data has changed significantly.
    Returns 204 on success, 404 if batch not found.
    Route placed BEFORE /{batch_name} DELETE to prevent path-parameter greedy matching.
    """
    from app.services.authority.cache import clear_cache
    _ensure_batch_name(batch_name)
    batch_dir = Path(dep_settings.BATCHES_DIR) / batch_name
    if not batch_dir.exists():
        raise HTTPException(status_code=404, detail="Batch not found")
    clear_cache(batch_dir)
    return Response(status_code=204)


@router.delete("/{batch_name}", status_code=204)
def delete_batch(batch_name: str, request: Request):
    """
    Deletes a batch directory and removes its history entry.
    Returns 204 on success, 404 if batch not found.
    """
    _ensure_batch_name(batch_name)
    _ensure_no_retry_recovery(batch_name)

    try:
        deleted = batch_manager.delete_batch(batch_name)
    except RuntimeError as exc:
        log_event(
            "batch.delete",
            result="failure",
            target=batch_name,
            request=request,
        )
        raise HTTPException(
            status_code=409,
            detail="Batch cannot be deleted while a run is active",
        ) from exc

    if not deleted:
        log_event("batch.delete", result="failure", target=batch_name, request=request)
        raise HTTPException(status_code=404, detail=f"Batch '{batch_name}' not found")
    log_event("batch.delete", target=batch_name, request=request)
    return None


@router.post("/{batch_name}/export-event")
async def report_export_event(batch_name: str, event: ExportEvent, request: Request):
    """Record an export lifecycle event from the frontend (audit I-2).

    Exports are generated client-side, so the frontend calls this to make them
    auditable. For a final METS/MODS ingest export (`is_final_ingest`), and when
    AUTO_PURGE_AFTER_EXPORT is enabled, the batch's working data is purged
    afterwards (audit I-3). The `.exporting` marker guards against retention
    racing an in-flight export.
    """
    _ensure_batch_name(batch_name)
    if not batch_manager.get_batch_path(batch_name).exists():
        raise HTTPException(status_code=404, detail="Batch not found")

    if event.phase == "started":
        batch_manager.set_exporting(batch_name, True)
        log_event("export.start", target=batch_name, request=request, format=event.format)
        return {"ok": True}

    # phase == "completed"
    batch_manager.set_exporting(batch_name, False)
    log_event("export.complete", target=batch_name, request=request,
              format=event.format, is_final_ingest=event.is_final_ingest)

    purged = False
    if event.is_final_ingest and settings.AUTO_PURGE_AFTER_EXPORT:
        if not batch_manager.is_run_active(batch_name):
            try:
                batch_manager.purge_batch_data(batch_name)
                purged = True
                log_event("batch.purge", target=batch_name, request=request, mode="auto-after-export")
            except Exception as exc:
                logger.error("Auto-purge after export failed for %s: exception_type=%s", batch_name, type(exc).__name__)
                log_event("batch.purge", result="failure", target=batch_name, request=request, mode="auto-after-export")
    return {"ok": True, "purged": purged}


@router.get("/retention/preview")
async def retention_preview():
    """Dry-run: show which completed batches WOULD be auto-purged now and why
    others are skipped. Never deletes anything (audit I-3)."""
    from app.services.retention import preview_purgeable
    return preview_purgeable()


@router.post("/retention/purge")
def retention_purge(request: Request):
    """Run the retention sweep now (purges eligible completed batches). No-op
    unless RETENTION_DAYS > 0. Each purge is audit-logged."""
    from app.services.retention import run_retention_sweep
    return run_retention_sweep(request=request)


@router.post("/{batch_name}/purge", status_code=200)
def purge_batch(batch_name: str, request: Request):
    """Explicit curator action: immediately purge all personal/working data for a
    batch (images, temp derivatives, checkpoint, authority cache), keeping only a
    minimal non-sensitive tombstone for accountability. Refuses while a run or
    export is in progress (audit I-3)."""
    _ensure_batch_name(batch_name)
    _ensure_no_retry_recovery(batch_name)
    if batch_manager.is_run_active(batch_name):
        raise HTTPException(status_code=409, detail="A run is in progress for this batch")
    if batch_manager.is_exporting(batch_name):
        raise HTTPException(status_code=409, detail="An export is in progress for this batch")
    try:
        existed = batch_manager.purge_batch_data(batch_name)
    except TransactionError:
        log_event("batch.purge", result="failure", target=batch_name, request=request, mode="manual")
        raise
    except Exception as exc:
        logger.error("Manual purge failed for %s: exception_type=%s", batch_name, type(exc).__name__)
        log_event("batch.purge", result="failure", target=batch_name, request=request, mode="manual")
        raise HTTPException(status_code=500, detail="Purge failed")
    if not existed:
        raise HTTPException(status_code=404, detail=f"Batch '{batch_name}' not found")
    log_event("batch.purge", target=batch_name, request=request, mode="manual")
    return {"message": "Batch data purged", "batch_name": batch_name}


def _revalidation_revision(batch_path: Path):
    return tuple(hashlib.sha256((batch_path / name).read_bytes()).digest() for name in ("config.json", "checkpoint.json"))


def _revalidation_snapshot(batch_path: Path):
    _assert_mutable(batch_path)
    if not (batch_path / "config.json").exists() or not (batch_path / "checkpoint.json").exists():
        raise HTTPException(status_code=404, detail="Batch not found or has no results")
    config_bytes = (batch_path / "config.json").read_bytes()
    config = json.loads(config_bytes)
    results, audit, checkpoint_revision = read_checkpoint_snapshot(batch_path / "checkpoint.json")
    return config, results, audit, (hashlib.sha256(config_bytes).digest(), checkpoint_revision)


@router.post("/{batch_name}/revalidate")
async def revalidate_batch(batch_name: str):
    _ensure_batch_name(batch_name)
    batch_path = batch_manager.get_batch_path(batch_name)
    config, results, audit, revision = await _batch_http(batch_path, lambda: _revalidation_snapshot(batch_path))
    response = await _joined_calculation(lambda: _calculate_revalidation(config, results))
    if not config.get("field_rules"):
        return response

    def commit():
        _assert_mutable(batch_path)
        try:
            unchanged = _revalidation_revision(batch_path) == revision
        except FileNotFoundError:
            unchanged = False
        if not unchanged:
            raise HTTPException(status_code=409, detail="Batch changed during revalidation (batch_revision_conflict); reload and retry")
        write_checkpoint(batch_path / "checkpoint.json", results, audit)
    await _batch_http(batch_path, commit)
    return response


def _calculate_revalidation(config, results):
    field_rules = config.get("field_rules")
    corrector_enabled = config.get("corrector_enabled", False)
    corrector_cap = config.get("corrector_cap", 100)
    group_labels = group_util.group_labels(config.get("field_groups"))

    if not field_rules:
        return {"message": "No field rules configured", "validated_count": 0}

    import threading
    cap_state = {"used": 0, "cap": corrector_cap or 100, "lock": threading.Lock()}
    api_key = settings.OPENROUTER_API_KEY

    from app.services.validation.runner import run_validation
    updated = 0
    for r in results:
        if r.get("success") and r.get("data"):
            outcomes = run_validation(
                data=r["data"],
                field_rules=field_rules,
                corrector_enabled=corrector_enabled,
                cap_state=cap_state,
                api_key=api_key,
                skip_fields=group_labels,
            )
            # A group's outcome describes the shape the model returned, which only
            # extraction can observe: data[group] already holds the normalised
            # array, so it cannot be re-derived here. Carry it over instead of
            # dropping the malformed-group indicator on every revalidation.
            preserved = {
                label: outcome
                for label, outcome in (r.get("validation") or {}).items()
                if label in group_labels
            }
            r["validation"] = {**outcomes, **preserved} or None
            updated += 1

    return {
        "message": "Revalidation complete",
        "validated_count": updated,
        "corrector_calls_used": cap_state["used"],
    }


@router.post("/{batch_name}/start")
@limiter.limit(settings.RATE_LIMIT_START)
async def start_batch(request: Request, batch_name: str, background_tasks: BackgroundTasks, body: BatchStartRequest = BatchStartRequest()):
    """
    Starts OCR processing for a batch. Accepts optional provider selection in the request body.
    Enforces a single active run per batch (409 if one is already in progress).
    """
    _ensure_batch_name(batch_name)
    batch_path = batch_manager.get_batch_path(batch_name)
    frozen_model = await _prepare_http(batch_path, lambda state: _start_preparation(request, batch_name, body, state))

    log_event(
        "batch.start",
        target=batch_name,
        request=request,
        provider=body.provider,
        requested_model=frozen_model,
        provider_host=provider_endpoint_host(body.provider),
    )
    background_tasks.add_task(run_ocr_task, batch_name)
    return {
        "message": "Batch processing started",
        "batch_name": batch_name,
        "provider": body.provider,
        "model": frozen_model,
    }


def _start_preparation(request, batch_name, body, reservation):
    _ensure_no_retry_recovery(batch_name)
    batch_path = batch_manager.get_batch_path(batch_name)
    if not batch_path.exists():
        raise HTTPException(status_code=404, detail="Batch not found")

    # Resolve provider + effective model before taking the run lock. This both
    # fails closed for unknown/disabled providers and freezes a provider default
    # (e.g. GPUStack's stable-vlm alias) into config.json for later retries.
    try:
        _endpoint, frozen_model, _key = _resolve_provider(body.provider, body.model)
    except ProviderConfigurationError as exc:
        report_error(logger, exc.code, "batch.start", exc, scope=request.scope)
        raise HTTPException(status_code=400, detail="Extraction provider configuration is invalid") from exc

    # Single-active-run lock: reject a second concurrent start (W-06/M-6)
    if not batch_manager.acquire_batch_lock(batch_name):
        raise HTTPException(status_code=409, detail="A run is already in progress for this batch")

    reservation["owned"] = True

    # Persist provider choice into config.json so run_ocr_task can pick it up.
    # If anything fails before the task is scheduled, release the lock we just took.
    try:
        config_path = batch_path / "config.json"
        if config_path.exists():
            with open(config_path, "r") as f:
                config = json.load(f)
        else:
            config = {}
        config["provider"] = body.provider
        config["model"] = frozen_model
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)
    except Exception:
        reservation["owned"] = False
        batch_manager.release_batch_lock(batch_name)
        raise

    return frozen_model


@router.get("/{batch_name}/results")
async def get_batch_results(batch_name: str) -> Dict[str, Any]:
    """
    Returns the checkpoint.json contents for a batch as {results: [...], audit: [...]}.
    Handles both legacy flat-array format (auto-migrated on read) and new object format.
    Returns {results: [], audit: []} if no checkpoint exists yet.
    """
    _ensure_batch_name(batch_name)
    batch_path = batch_manager.get_batch_path(batch_name)
    if not batch_path.exists():
        raise HTTPException(status_code=404, detail="Batch not found")

    checkpoint_path = batch_path / "checkpoint.json"
    if not checkpoint_path.exists():
        return {"results": [], "audit": []}

    try:
        results, audit = read_checkpoint(checkpoint_path)
        return {"results": results, "audit": audit}
    except Exception:
        logger.error("Failed to read checkpoint for batch %s", batch_name)
        raise HTTPException(status_code=500, detail="Failed to read results")


@router.post("/{batch_name}/cancel")
async def cancel_batch(batch_name: str, request: Request) -> Dict[str, Any]:
    """
    Sets a cancellation flag that stops OCR after the current image completes.
    Cancelling a non-running batch is a no-op — reported as ``cancelled: false``
    rather than as a success, so a stale view cannot show a cancellation that
    never happened.
    """
    _ensure_batch_name(batch_name)
    cancelled = ws_manager.cancel_batch(batch_name)
    log_event("batch.cancel", result="success" if cancelled else "failure",
              target=batch_name, request=request)
    return {
        "message": (
            "Cancel requested — stopping after the current image"
            if cancelled
            else "No run is in progress for this batch — nothing to cancel"
        ),
        "batch_name": batch_name,
        "cancelled": cancelled,
    }


def _ensure_no_retry_recovery(batch_name: str) -> None:
    if batch_manager.retry_recovery_required(batch_name):
        raise HTTPException(status_code=409, detail="Retry recovery required; batch remains locked. Contact the administrator.")


class RetryRecoveryRequired(CheckpointError):
    code = "retry_recovery_required"


def _prepare_retry_images(batch_path: Path, files: List[Path], *, remove_result: Optional[str] = None) -> None:
    """Prepare under the existing run lock; compensate caught failures locally.

    Same-directory filesystem renames avoid partial-copy failures. The atomic
    checkpoint writer retains its old file on failure. If compensation also
    fails, callers must KEEP the run lock for explicit operator recovery.
    """
    _ensure_no_retry_recovery(batch_path.name)
    checkpoint = batch_path / "checkpoint.json"
    try:
        results, audit = read_checkpoint(checkpoint)
        present = True
    except FileNotFoundError:
        results, audit, present = [], [], False
    plans = [(source, batch_path / source.name) for source in files]
    if any(destination.exists() for _, destination in plans):
        raise HTTPException(status_code=409, detail="Retry destination already exists")
    moved = []
    try:
        batch_manager.begin_retry_preparation(batch_path.name, files, (
            {"results": [r for r in results if r["filename"] != remove_result], "audit": audit}
            if present and remove_result is not None else None
        ))
    except Exception:
        if batch_manager.retry_recovery_required(batch_path.name):
            raise RetryRecoveryRequired() from None
        raise
    try:
        for source, destination in plans:
            source.rename(destination)
            moved.append((source, destination))
        if present and remove_result is not None:
            write_checkpoint(checkpoint, [r for r in results if r["filename"] != remove_result], audit)
    except Exception:
        recovery_failed = False
        for source, destination in reversed(moved):
            try:
                destination.rename(source)
            except Exception as rollback_exc:
                recovery_failed = True
                report_error(logger, "retry_recovery_required", "batch.retry.rollback", rollback_exc)
        if not recovery_failed:
            try:
                batch_manager.finish_retry_preparation(batch_path.name)
            except Exception:
                recovery_failed = True
        if recovery_failed:
            raise RetryRecoveryRequired() from None
        raise
    try:
        batch_manager.finish_retry_preparation(batch_path.name)
    except Exception:
        raise RetryRecoveryRequired() from None


@router.post("/{batch_name}/retry-image/{filename}")
async def retry_image(batch_name: str, filename: str, background_tasks: BackgroundTasks) -> Dict[str, str]:
    """
    Moves a single failed file from _errors/ back to the batch directory,
    removes its checkpoint entry so it gets re-processed, and starts OCR.
    Enforces a single active run per batch (409 if one is already in progress).
    """
    _ensure_batch_name(batch_name)
    await _prepare_http(batch_manager.get_batch_path(batch_name), lambda state: _retry_image_preparation(batch_name, filename, state))
    background_tasks.add_task(run_ocr_task, batch_name)
    return {"message": f"Retry started for {filename}", "batch_name": batch_name}


@router.post("/{batch_name}/retry")
async def retry_batch(batch_name: str, background_tasks: BackgroundTasks):
    """
    Retries processing for failed cards in a batch.
    Moves files from _errors back to main batch dir and starts processing.
    Enforces a single active run per batch (409 if one is already in progress).
    """
    _ensure_batch_name(batch_name)
    prepared = await _prepare_http(batch_manager.get_batch_path(batch_name), lambda state: _retry_batch_preparation(batch_name, state))
    if not prepared:
        return {"message": "No failed cards to retry", "batch_name": batch_name}
    background_tasks.add_task(run_ocr_task, batch_name, retry_errors=True)
    return {"message": "Retry processing started", "batch_name": batch_name}


def _retry_image_preparation(batch_name, filename, reservation):
    _ensure_no_retry_recovery(batch_name)
    _ensure_filename(filename)
    batch_path = batch_manager.get_batch_path(batch_name)
    if not batch_path.exists():
        raise HTTPException(status_code=404, detail="Batch not found")

    error_file = batch_path / "_errors" / filename
    if not error_file.exists():
        raise HTTPException(status_code=404, detail=f"File '{filename}' not found in _errors/")

    if not batch_manager.acquire_batch_lock(batch_name):
        raise HTTPException(status_code=409, detail="A run is already in progress for this batch")
    reservation["owned"] = True
    try:
        _prepare_retry_images(batch_path, [error_file], remove_result=filename)
        ws_manager.clear_cancel_event(batch_name)
    except Exception as exc:
        reservation["owned"] = False
        keep_lock = isinstance(exc, RetryRecoveryRequired)
        if not keep_lock:
            batch_manager.release_batch_lock(batch_name)
        if isinstance(exc, HTTPException):
            raise
        identifier = report_error(logger, "retry_recovery_required" if keep_lock else "retry_preparation_failed", "batch.retry.prepare", exc)
        raise HTTPException(status_code=500, detail=(
            "Retry recovery required; batch remains locked. Contact the administrator. "
            if keep_lock else "Retry preparation failed; no OCR was started. "
        ) + f"Reference: {identifier}") from None

    return True


def _retry_batch_preparation(batch_name, reservation):
    _ensure_no_retry_recovery(batch_name)
    batch_path = batch_manager.get_batch_path(batch_name)
    if not batch_path.exists():
        raise HTTPException(status_code=404, detail="Batch not found")

    error_dir = batch_path / "_errors"
    if not error_dir.exists() or not any(error_dir.iterdir()):
        return False

    if not batch_manager.acquire_batch_lock(batch_name):
        raise HTTPException(status_code=409, detail="A run is already in progress for this batch")

    reservation["owned"] = True
    try:
        _prepare_retry_images(batch_path, sorted(p for p in error_dir.iterdir() if p.is_file()))
    except Exception as exc:
        reservation["owned"] = False
        if not isinstance(exc, RetryRecoveryRequired):
            batch_manager.release_batch_lock(batch_name)
        if isinstance(exc, HTTPException):
            raise
        identifier = report_error(logger, "retry_recovery_required" if isinstance(exc, RetryRecoveryRequired) else "retry_preparation_failed", "batch.retry.prepare", exc)
        raise HTTPException(status_code=500, detail=("Retry recovery required; batch remains locked. Contact the administrator. " if isinstance(exc, RetryRecoveryRequired) else "Retry preparation failed; no OCR was started. ") + f"Reference: {identifier}") from None

    # Clear any stale cancel event before starting the retry
    ws_manager.clear_cancel_event(batch_name)

    return True
