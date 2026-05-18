import shutil
from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from fastapi.responses import Response
from typing import Any, Dict, List, Optional
import json
import logging

from app.services.batch_manager import batch_manager
from app.services.ocr_engine import ocr_engine
from app.services.ws_manager import ws_manager
from pathlib import Path
from app.models.schemas import AuditEntry, BatchCreate, BatchHistoryItem, BatchProgress, BatchResponse, BatchStartRequest, ResultPatch
from app.core.config import settings, get_settings, Settings

logger = logging.getLogger(__name__)

router = APIRouter()


def read_checkpoint(checkpoint_path: Path) -> tuple:
    """Read checkpoint.json. Returns (results_list, audit_list).
    Handles both legacy flat-array format and new {results, audit} object format.
    Auto-migrates legacy format on first read by writing back the wrapped object.
    """
    with open(checkpoint_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        # Legacy flat-array format — migrate to object format atomically
        obj = {"results": data, "audit": []}
        with open(checkpoint_path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        return data, []
    return data.get("results", []), data.get("audit", [])


def write_checkpoint(checkpoint_path: Path, results: list, audit: list) -> None:
    """Write results + audit back to checkpoint.json in the new object format."""
    with open(checkpoint_path, "w", encoding="utf-8") as f:
        json.dump({"results": results, "audit": audit}, f, ensure_ascii=False, indent=2)


def _resolve_provider(provider: str, model: Optional[str] = None):
    """Returns (api_endpoint, model_name, api_key) for the given provider."""
    if provider == "ollama":
        return settings.OLLAMA_API_ENDPOINT, model or settings.OLLAMA_MODEL_NAME, settings.OLLAMA_API_KEY
    return settings.API_ENDPOINT, model or settings.MODEL_NAME, settings.OPENROUTER_API_KEY


async def run_ocr_task(batch_name: str, resume: bool = True, retry_errors: bool = False):
    """Background task to run OCR on a batch."""
    # Get (or create) the cancel event and immediately clear it to ensure a fresh state.
    # This prevents a stale set event from a previous cancellation aborting the new run.
    cancel_event = ws_manager.get_or_create_cancel_event(batch_name)
    cancel_event.clear()

    try:
        batch_path = batch_manager.get_batch_path(batch_name)
        config_path = batch_path / "config.json"

        fields = None
        prompt_template = None
        provider = "openrouter"
        model = None
        field_rules = None
        corrector_enabled = False
        corrector_cap = 100
        if config_path.exists():
            with open(config_path, "r") as f:
                config = json.load(f)
                fields = config.get("fields")
                prompt_template = config.get("prompt_template")
                provider = config.get("provider", "openrouter")
                model = config.get("model")
                field_rules = config.get("field_rules")
                corrector_enabled = config.get("corrector_enabled", False)
                corrector_cap = config.get("corrector_cap", 100)

        api_endpoint, model_name, api_key = _resolve_provider(provider, model)

        # If retry_errors is True, move files back from _errors so ocr_engine can process them.
        if retry_errors:
            error_dir = batch_path / "_errors"
            if error_dir.exists():
                for item in error_dir.iterdir():
                    if item.is_file():
                        shutil.move(str(item), str(batch_path / item.name))

        await ocr_engine.process_batch(
            batch_dir=batch_path,
            fields=fields,
            progress_callback=ws_manager.broadcast_progress,
            resume=resume,
            cancel_event=cancel_event,
            prompt_template=prompt_template,
            api_endpoint=api_endpoint,
            model_name=model_name,
            api_key=api_key,
            field_rules=field_rules,
            corrector_enabled=corrector_enabled,
            corrector_cap=corrector_cap,
        )

        # Mark as completed (or cancelled) in a final progress update
        last_state = ws_manager.batch_states.get(batch_name)
        if last_state:
            if cancel_event.is_set():
                last_state.status = "cancelled"
            else:
                last_state.status = "completed"
            await ws_manager.broadcast_progress(batch_name, last_state)
        else:
            # Edge case: no progress was ever broadcast — send completed/cancelled with zeroed progress
            status = "cancelled" if cancel_event.is_set() else "completed"
            final_state = BatchProgress(
                batch_name=batch_name,
                current=0,
                total=0,
                percentage=0.0,
                status=status,
            )
            await ws_manager.broadcast_progress(batch_name, final_state)

        # Persist final status to batches.json
        final_status = "cancelled" if cancel_event.is_set() else "completed"
        batch_manager.update_batch_status(batch_name, final_status)

    except Exception as e:
        logger.exception(f"Error in background OCR task for {batch_name}: {e}")
        error_msg = str(e)
        last_state = ws_manager.batch_states.get(batch_name)
        if last_state:
            last_state.status = "failed"
            last_state.error = error_msg
            await ws_manager.broadcast_progress(batch_name, last_state)
        else:
            # No progress was ever broadcast — create minimal failed state
            failed_state = BatchProgress(
                batch_name=batch_name,
                current=0,
                total=0,
                percentage=0.0,
                status="failed",
                error=error_msg,
            )
            await ws_manager.broadcast_progress(batch_name, failed_state)
        # Persist failed status to batches.json
        batch_manager.update_batch_status(batch_name, "failed")
    finally:
        # Clean up cancel event after the task ends (success, cancel, or failure)
        ws_manager.clear_cancel_event(batch_name)


@router.post("/", response_model=BatchResponse)
async def create_batch(batch_data: BatchCreate):
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

        batch_name = batch_manager.create_batch(
            custom_name=batch_data.custom_name,
            session_id=batch_data.session_id,
            fields=batch_data.fields,
            prompt_template=batch_data.prompt_template,
            field_rules=fr,
            corrector_enabled=batch_data.corrector_enabled,
            corrector_cap=batch_data.corrector_cap,
            authority_bindings=ab,
        )

        batch_path = batch_manager.get_batch_path(batch_name)
        files_count = len([f for f in batch_path.iterdir() if f.is_file() and f.suffix.lower() in [".jpg", ".jpeg"]])

        return BatchResponse(
            batch_name=batch_name,
            status="uploaded",
            files_count=files_count
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create batch: {str(e)}")


@router.get("/", response_model=List[str])
async def list_batches():
    """
    Lists all permanent batches.
    """
    return batch_manager.list_batches()


@router.get("/history", response_model=List[BatchHistoryItem])
async def get_batch_history():
    """
    Returns full batch history with enriched metadata (file counts, error counts).
    Route placed before /{batch_name} routes to prevent FastAPI treating 'history' as a parameter.
    """
    return batch_manager.get_history()


@router.patch("/{batch_name}/results/{filename}", response_model=dict)
async def patch_result(
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
    batch_dir = Path(settings.BATCHES_DIR) / batch_name
    checkpoint_path = batch_dir / "checkpoint.json"
    if not checkpoint_path.exists():
        raise HTTPException(status_code=404, detail="Checkpoint not found")
    results, audit = read_checkpoint(checkpoint_path)
    # Find matching result row by filename
    found = False
    for row in results:
        if row.get("filename") == filename:
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
    batch_dir = Path(dep_settings.BATCHES_DIR) / batch_name
    if not batch_dir.exists():
        raise HTTPException(status_code=404, detail="Batch not found")
    clear_cache(batch_dir)
    return Response(status_code=204)


@router.delete("/{batch_name}", status_code=204)
async def delete_batch(batch_name: str):
    """
    Deletes a batch directory and removes its history entry.
    Returns 204 on success, 404 if batch not found.
    """
    deleted = batch_manager.delete_batch(batch_name)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Batch '{batch_name}' not found")
    return None


@router.post("/{batch_name}/revalidate")
async def revalidate_batch(batch_name: str):
    """
    Re-runs validation rules against an existing batch's checkpoint.json without re-extracting.
    Reads field_rules from config.json, applies run_validation to each successful result,
    writes updated validation maps back to checkpoint.json.
    Returns 404 if batch or checkpoint not found; returns early if no field_rules configured.
    """
    batch_path = batch_manager.get_batch_path(batch_name)
    config_path = batch_path / "config.json"
    checkpoint_path = batch_path / "checkpoint.json"

    if not config_path.exists() or not checkpoint_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Batch '{batch_name}' not found or has no results"
        )

    with open(config_path) as f:
        config = json.load(f)
    field_rules = config.get("field_rules")
    corrector_enabled = config.get("corrector_enabled", False)
    corrector_cap = config.get("corrector_cap", 100)

    if not field_rules:
        return {"message": "No field rules configured", "validated_count": 0}

    results, audit = read_checkpoint(checkpoint_path)

    import threading
    cap_state = {"used": 0, "cap": corrector_cap or 100, "lock": threading.Lock()}
    api_key = settings.OPENROUTER_API_KEY

    from app.services.validation.runner import run_validation
    updated = 0
    for r in results:
        if r.get("success") and r.get("data"):
            r["validation"] = run_validation(
                data=r["data"],
                field_rules=field_rules,
                corrector_enabled=corrector_enabled,
                cap_state=cap_state,
                api_key=api_key,
            ) or None
            updated += 1

    write_checkpoint(checkpoint_path, results, audit)  # audit unchanged

    return {
        "message": "Revalidation complete",
        "validated_count": updated,
        "corrector_calls_used": cap_state["used"],
    }


@router.post("/{batch_name}/start")
async def start_batch(batch_name: str, background_tasks: BackgroundTasks, body: BatchStartRequest = BatchStartRequest()):
    """
    Starts OCR processing for a batch. Accepts optional provider selection in the request body.
    """
    batch_path = batch_manager.get_batch_path(batch_name)
    if not batch_path.exists():
        raise HTTPException(status_code=404, detail="Batch not found")

    # Persist provider choice into config.json so run_ocr_task can pick it up
    config_path = batch_path / "config.json"
    if config_path.exists():
        with open(config_path, "r") as f:
            config = json.load(f)
    else:
        config = {}
    config["provider"] = body.provider
    if body.model:
        config["model"] = body.model
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    background_tasks.add_task(run_ocr_task, batch_name)
    return {"message": "Batch processing started", "batch_name": batch_name, "provider": body.provider, "model": body.model}


@router.get("/{batch_name}/results")
async def get_batch_results(batch_name: str) -> Dict[str, Any]:
    """
    Returns the checkpoint.json contents for a batch as {results: [...], audit: [...]}.
    Handles both legacy flat-array format (auto-migrated on read) and new object format.
    Returns {results: [], audit: []} if no checkpoint exists yet.
    """
    batch_path = batch_manager.get_batch_path(batch_name)
    if not batch_path.exists():
        raise HTTPException(status_code=404, detail="Batch not found")

    checkpoint_path = batch_path / "checkpoint.json"
    if not checkpoint_path.exists():
        return {"results": [], "audit": []}

    try:
        results, audit = read_checkpoint(checkpoint_path)
        return {"results": results, "audit": audit}
    except Exception as e:
        logger.error(f"Failed to read checkpoint for batch {batch_name}: {e}")
        raise HTTPException(status_code=500, detail="Failed to read results")


@router.post("/{batch_name}/cancel")
async def cancel_batch(batch_name: str) -> Dict[str, str]:
    """
    Sets a cancellation flag that stops OCR after the current image completes.
    Cancelling a non-running batch is a no-op.
    """
    ws_manager.cancel_batch(batch_name)
    return {"message": "Cancel requested", "batch_name": batch_name}


@router.post("/{batch_name}/retry-image/{filename}")
async def retry_image(batch_name: str, filename: str, background_tasks: BackgroundTasks) -> Dict[str, str]:
    """
    Moves a single failed file from _errors/ back to the batch directory,
    removes its checkpoint entry so it gets re-processed, and starts OCR.
    """
    batch_path = batch_manager.get_batch_path(batch_name)
    if not batch_path.exists():
        raise HTTPException(status_code=404, detail="Batch not found")

    error_file = batch_path / "_errors" / filename
    if not error_file.exists():
        raise HTTPException(status_code=404, detail=f"File '{filename}' not found in _errors/")

    # Move file back to batch directory
    shutil.move(str(error_file), str(batch_path / filename))

    # Remove the entry from checkpoint.json so the image gets re-processed
    checkpoint_path = batch_path / "checkpoint.json"
    if checkpoint_path.exists():
        try:
            results, audit = read_checkpoint(checkpoint_path)
            results = [r for r in results if r.get("filename") != filename]
            write_checkpoint(checkpoint_path, results, audit)  # audit unchanged
        except Exception as e:
            logger.error(f"Failed to update checkpoint for retry of {filename}: {e}")

    # Clear any stale cancel event so the retry doesn't abort immediately
    ws_manager.clear_cancel_event(batch_name)

    background_tasks.add_task(run_ocr_task, batch_name)
    return {"message": f"Retry started for {filename}", "batch_name": batch_name}


@router.post("/{batch_name}/retry")
async def retry_batch(batch_name: str, background_tasks: BackgroundTasks):
    """
    Retries processing for failed cards in a batch.
    Moves files from _errors back to main batch dir and starts processing.
    """
    batch_path = batch_manager.get_batch_path(batch_name)
    if not batch_path.exists():
        raise HTTPException(status_code=404, detail="Batch not found")

    error_dir = batch_path / "_errors"
    if not error_dir.exists() or not any(error_dir.iterdir()):
        return {"message": "No failed cards to retry", "batch_name": batch_name}

    # Clear any stale cancel event before starting the retry
    ws_manager.clear_cancel_event(batch_name)

    background_tasks.add_task(run_ocr_task, batch_name, retry_errors=True)
    return {"message": "Retry processing started", "batch_name": batch_name}
