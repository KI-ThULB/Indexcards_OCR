"""REST surface for bulk / multi-batch processing.

Every route reuses the existing security stack: the router is registered with
the same ``Depends(require_auth)`` bearer guard as every other HTTP router,
folder names go through the import layer's path validation, run ids are uuid4,
and creating or starting a run is rate limited. The WebSocket keeps its existing
Origin allow-list plus ``?token=`` check — bulk runs simply use another channel
id on the same endpoint.

While ``BULK_IMPORT_ROOT`` is unset every route here returns 404, so an
unconfigured deployment has no bulk attack surface at all.

Audit records carry run id, run name, folder/image counts, provider and the
resulting status — never extracted metadata, OCR text, prompts, image contents,
keys or tokens.
"""
import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from app.core.audit import log_event
from app.core.config import settings
from app.core.rate_limit import limiter
from app.models.schemas import (
    BulkProgress,
    BulkRunCreate,
    BulkSourceFolder,
    BulkSourcesResponse,
)
from app.services import bulk_export, bulk_import, bulk_orchestrator
from app.services.bulk_manager import (
    RESUMABLE_STATUSES,
    STATUS_QUEUED,
    STATUS_RUNNING,
    bulk_manager,
)
from app.services.bulk_progress import to_progress
from app.services.ocr_engine import ocr_engine
from app.services.template_service import template_service

logger = logging.getLogger(__name__)


async def require_bulk_enabled() -> None:
    """404 the whole feature unless an import root is configured.

    Deliberately a 404 rather than a 403: an unconfigured deployment should not
    even advertise that the feature exists.
    """
    if not bulk_import.is_enabled():
        raise HTTPException(status_code=404, detail="Bulk processing is not configured")


router = APIRouter(dependencies=[Depends(require_bulk_enabled)])


def _get_run_or_404(bulk_run_id: str) -> Dict[str, Any]:
    run = bulk_manager.get_run(bulk_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Bulk run not found")
    return run


# --------------------------------------------------------------------------- #
# Sources
# --------------------------------------------------------------------------- #
@router.get("/sources", response_model=BulkSourcesResponse)
async def list_sources() -> BulkSourcesResponse:
    """The import root's immediate subfolders with their supported-image counts.

    Only names and counts leave the backend — never the root path itself.
    """
    try:
        listing = bulk_import.list_source_folders()
    except bulk_import.BulkImportDisabled:
        raise HTTPException(status_code=404, detail="Bulk processing is not configured")
    except OSError:
        logger.exception("Could not read BULK_IMPORT_ROOT")
        raise HTTPException(status_code=500, detail="Could not read the import root")
    return BulkSourcesResponse(
        root_configured=True,
        folders=[BulkSourceFolder(**f) for f in listing["folders"]],
        truncated=bool(listing["truncated"]),
    )


# --------------------------------------------------------------------------- #
# Create
# --------------------------------------------------------------------------- #
@router.post("/runs", response_model=BulkProgress)
@limiter.limit(settings.RATE_LIMIT_BULK_START)
async def create_run(request: Request, body: BulkRunCreate) -> BulkProgress:
    """Create a bulk run from a template and a selection of source folders.

    ``folders`` are names taken from ``GET /bulk/sources``; each is re-resolved
    against the import root here, so a name that did not come from that listing
    is rejected. The template's field list is validated and then **frozen** into
    the run, so a later template edit cannot shift CSV columns mid-run.
    """
    template = template_service.get_template(body.template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    if not template.fields:
        raise HTTPException(
            status_code=400, detail="The selected template has an empty field list"
        )
    if not body.folders:
        raise HTTPException(status_code=400, detail="Select at least one source folder")
    if len(body.folders) != len(set(body.folders)):
        raise HTTPException(status_code=400, detail="Duplicate source folders selected")
    if len(body.folders) > settings.BULK_MAX_FOLDERS:
        raise HTTPException(
            status_code=400,
            detail=f"At most {settings.BULK_MAX_FOLDERS} folders can be processed in one run",
        )
    if body.provider not in ("openrouter", "ollama"):
        raise HTTPException(status_code=400, detail="Unknown provider")

    # Resolve and count every folder up front, so a typo or a vanished folder is
    # reported now rather than hours into an unattended run.
    folders: List[Dict[str, Any]] = []
    for name in body.folders:
        try:
            path = bulk_import.resolve_source_folder(name)
            count = len(bulk_import.source_images(path))
        except bulk_import.BulkImportError:
            raise HTTPException(status_code=400, detail=f"Unknown source folder: {name}")
        except OSError:
            raise HTTPException(status_code=400, detail=f"Unreadable source folder: {name}")
        if count == 0:
            raise HTTPException(
                status_code=400, detail=f"Source folder contains no supported images: {name}"
            )
        folders.append({"source_folder": name, "images_total": count})

    # When the template asks for a picture description, run_ocr_task adds that
    # field to the effective list — so it must be part of the frozen schema too,
    # or the extracted value would be dropped from the CSV as an unknown key.
    schema_fields = list(template.fields)
    if template.describe_pictures and ocr_engine.PICTURE_FIELD not in schema_fields:
        schema_fields.append(ocr_engine.PICTURE_FIELD)

    field_rules = None
    if template.field_rules:
        field_rules = {
            k: (v.dict() if hasattr(v, "dict") else v) for k, v in template.field_rules.items()
        }
    authority_bindings = None
    if template.authority_bindings:
        authority_bindings = {
            k: (v.dict() if hasattr(v, "dict") else v)
            for k, v in template.authority_bindings.items()
        }

    run = bulk_manager.create_run(
        name=body.name,
        template_id=template.id,
        schema_fields=schema_fields,
        provider=body.provider,
        model=body.model,
        folders=folders,
        prompt_template=template.prompt_template,
        field_rules=field_rules,
        authority_bindings=authority_bindings,
        describe_pictures=bool(template.describe_pictures),
    )
    run["output_csv"] = str(bulk_manager.export_csv_path(run["bulk_run_id"]))
    bulk_manager.save_run(run)

    log_event(
        "bulk_run_created",
        target=run["bulk_run_id"],
        request=request,
        run_name=run["name"],
        folders=run["folders_total"],
        images=run["images_total"],
        provider=run["provider"],
    )
    return to_progress(run)


# --------------------------------------------------------------------------- #
# Lifecycle
# --------------------------------------------------------------------------- #
async def _begin(request: Request, bulk_run_id: str, *, action: str) -> BulkProgress:
    """Shared start/resume handling."""
    run = _get_run_or_404(bulk_run_id)
    try:
        run = await bulk_orchestrator.start_run(bulk_run_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Bulk run not found")
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))

    log_event(
        action,
        target=bulk_run_id,
        request=request,
        run_name=run.get("name"),
        folders=run.get("folders_total"),
        folders_completed=run.get("folders_completed"),
        provider=run.get("provider"),
    )
    return to_progress(run)


@router.post("/runs/{bulk_run_id}/start", response_model=BulkProgress)
@limiter.limit(settings.RATE_LIMIT_BULK_START)
async def start_run(request: Request, bulk_run_id: str) -> BulkProgress:
    """Start a queued run. Use /resume for a paused or interrupted one."""
    run = _get_run_or_404(bulk_run_id)
    if run.get("status") != STATUS_QUEUED:
        raise HTTPException(
            status_code=409,
            detail=f"Run is {run.get('status')}, not {STATUS_QUEUED} — use resume instead",
        )
    return await _begin(request, bulk_run_id, action="bulk_run_started")


@router.post("/runs/{bulk_run_id}/resume", response_model=BulkProgress)
@limiter.limit(settings.RATE_LIMIT_BULK_START)
async def resume_run(request: Request, bulk_run_id: str) -> BulkProgress:
    """Resume a paused or interrupted run.

    This is the only way a run that was interrupted by a backend restart starts
    sending images to the model again — nothing resumes automatically (D2).
    Folders already completed are skipped and, within the interrupted folder,
    images already extracted are never re-sent.
    """
    run = _get_run_or_404(bulk_run_id)
    if run.get("status") not in RESUMABLE_STATUSES:
        raise HTTPException(
            status_code=409, detail=f"Run is {run.get('status')} and cannot be resumed"
        )
    return await _begin(request, bulk_run_id, action="bulk_run_resumed")


@router.post("/runs/{bulk_run_id}/pause", response_model=BulkProgress)
async def pause_run(request: Request, bulk_run_id: str) -> BulkProgress:
    """Stop after the current image, keeping every completed result."""
    run = _get_run_or_404(bulk_run_id)
    if run.get("status") != STATUS_RUNNING:
        raise HTTPException(status_code=409, detail=f"Run is {run.get('status')}, not running")
    bulk_orchestrator.request_pause(bulk_run_id)
    log_event("bulk_run_paused", target=bulk_run_id, request=request, run_name=run.get("name"))
    return to_progress(_get_run_or_404(bulk_run_id))


@router.post("/runs/{bulk_run_id}/cancel", response_model=BulkProgress)
async def cancel_run(request: Request, bulk_run_id: str) -> BulkProgress:
    """Cancel after the current image. Completed results and batches are kept."""
    run = _get_run_or_404(bulk_run_id)
    if run.get("status") != STATUS_RUNNING:
        raise HTTPException(status_code=409, detail=f"Run is {run.get('status')}, not running")
    bulk_orchestrator.request_cancel(bulk_run_id)
    log_event("bulk_run_cancelled", target=bulk_run_id, request=request, run_name=run.get("name"))
    return to_progress(_get_run_or_404(bulk_run_id))


# --------------------------------------------------------------------------- #
# Read
# --------------------------------------------------------------------------- #
@router.get("/runs", response_model=List[BulkProgress])
async def list_runs() -> List[BulkProgress]:
    """All bulk runs, newest first."""
    return [to_progress(run) for run in bulk_manager.list_runs()]


@router.get("/runs/{bulk_run_id}", response_model=BulkProgress)
async def get_run(bulk_run_id: str) -> BulkProgress:
    """One run's full state, including per-folder progress."""
    return to_progress(_get_run_or_404(bulk_run_id))


# --------------------------------------------------------------------------- #
# Export
# --------------------------------------------------------------------------- #
def _download_name(run: Dict[str, Any], suffix: str) -> str:
    """A safe download filename derived from the run name.

    The run name is operator-supplied display text, so it is reduced to a
    conservative character set here. It is never used as a path on the server.
    """
    raw = str(run.get("name") or "bulk_run")
    safe = "".join(c if (c.isalnum() or c in "-_") else "_" for c in raw).strip("_")
    return f"{safe or 'bulk_run'}_{suffix}"


@router.get("/runs/{bulk_run_id}/export.csv")
async def export_csv(request: Request, bulk_run_id: str) -> FileResponse:
    """The consolidated, provenance-bearing CSV for the whole run.

    Generated to the run's directory (streamed, bounded memory) and served from
    there, so the operator has a stable artefact alongside the run state.
    """
    run = _get_run_or_404(bulk_run_id)
    try:
        path = bulk_export.write_consolidated_csv(
            run, bulk_manager.export_csv_path(bulk_run_id)
        )
    except Exception:
        logger.exception("Consolidated export failed for bulk run %s", bulk_run_id)
        log_event("bulk_run_exported", result="failure", target=bulk_run_id, request=request)
        raise HTTPException(status_code=500, detail="Export failed")

    rows, failures = bulk_export.row_counts(run)
    log_event(
        "bulk_run_exported",
        target=bulk_run_id,
        request=request,
        run_name=run.get("name"),
        format="csv",
        rows=rows,
        failed_records=failures,
    )
    return FileResponse(
        str(path),
        media_type="text/csv; charset=utf-8",
        filename=_download_name(run, "consolidated.csv"),
    )


@router.get("/runs/{bulk_run_id}/failures.csv")
async def export_failures_csv(bulk_run_id: str) -> StreamingResponse:
    """Failed image records, so they can be retried selectively via the existing
    per-image retry endpoint instead of rerunning the collection."""
    run = _get_run_or_404(bulk_run_id)
    filename = _download_name(run, "failures.csv")
    return StreamingResponse(
        bulk_export.iter_failures_csv(run),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
