from app.core.transactions import TransactionError, TransactionTimeout
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.api_v1.api import api_router
from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.delivery import DeliveryErrorBoundary
from app.core.error_reporting import report_error
from app.core.security import validate_batch_name, validate_filename

logger = logging.getLogger(__name__)

# Explicit content types for the image route — never trust the file extension blindly.
_IMAGE_CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.api.api_v1.endpoints.batches import _joined_calculation
    # Startup: clean orphaned temp sessions
    from app.services.batch_manager import batch_manager
    cleaned = batch_manager.cleanup_stale_sessions()
    if cleaned > 0:
        logger.info(f"Cleaned up {cleaned} stale temp session(s)")
    # Startup: run one retention sweep (no-op unless RETENTION_DAYS > 0). A
    # periodic sweep would need a scheduler; startup + the manual endpoint cover
    # the single-instance deployment. See docs/DEPLOYMENT.md.
    from app.services.retention import run_retention_sweep
    result = await _joined_calculation(run_retention_sweep)
    if result.get("purged"):
        logger.info(f"Retention sweep purged {len(result['purged'])} batch(es) at startup")
    # Startup: a bulk run recorded as "running" belongs to a process that no
    # longer exists, so mark it "interrupted" and stop. Deliberately NO
    # auto-resume — an unattended crash-loop or a routine redeploy must never
    # silently restart VLM spend. A human clicks Resume. See bulk_manager (D2).
    # Startup: make the AMIGA Tonband-Karteikarte template available. Idempotent,
    # and it never touches an existing template — including the older flat
    # "AMIGA Tonbandkartei", which stays exactly as it is.
    from app.services.amiga_template import TEMPLATE_NAME, ensure_seeded
    try:
        if await _joined_calculation(ensure_seeded):
            logger.info("Seeded template %r", TEMPLATE_NAME)
    except Exception as exc:
        # A seeding failure must never prevent the application from starting.
        logger.error("Could not seed the %r template: exception_type=%s", TEMPLATE_NAME, type(exc).__name__)

    from app.services.bulk_manager import bulk_manager
    interrupted = await _joined_calculation(bulk_manager.mark_interrupted_runs)
    if interrupted:
        logger.warning(
            "%d bulk run(s) marked interrupted at startup; explicit Resume required: %s",
            len(interrupted), ", ".join(interrupted),
        )
    yield
    # Shutdown: nothing needed


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach defense-in-depth security headers to every response (W-08/M-1/F-3)."""

    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
        except Exception as exc:
            # Starlette's outer 500 handler re-raises to the ASGI server, which
            # would log the sensitive exception and its chain again. Handle
            # request failures here before that boundary, with the same 500.
            response = await generic_exception_handler(request, exc)
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; object-src 'none'; "
            "frame-ancestors 'none'; base-uri 'self'",
        )
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        return response


# Docs/OpenAPI are gated behind ENABLE_DOCS so the API surface is not published
# without auth in production (W-07/H-6).
_docs_kwargs = (
    dict(openapi_url=f"{settings.API_V1_STR}/openapi.json", docs_url="/docs", redoc_url="/redoc")
    if settings.ENABLE_DOCS
    else dict(openapi_url=None, docs_url=None, redoc_url=None)
)

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    lifespan=lifespan,
    **_docs_kwargs,
)

# Rate limiting (W-06/H-2): attach the shared limiter and its 429 handler.
app.state.limiter = limiter
# slowapi's handler has a narrower signature than Starlette's type stub expects.
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

app.add_middleware(SecurityHeadersMiddleware)

# Optional restrictive CORS — only when explicitly configured (M-1).
if settings.cors_allow_origins:
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Outermost user middleware covers the complete inner response lifecycle.
app.add_middleware(DeliveryErrorBoundary)

# The bearer token (W-01) is applied per-router in api.py — HTTP routers require it,
# the WebSocket router does its own Origin+token check.
app.include_router(api_router, prefix=settings.API_V1_STR)

# Batch images directory — served through a validated route below, not StaticFiles.
batches_dir = Path(settings.BATCHES_DIR)
batches_dir.mkdir(parents=True, exist_ok=True)


@app.exception_handler(TransactionError)
async def registry_exception_handler(request: Request, exc: TransactionError):
    identifier = report_error(logger, exc.code, "registry.operation", exc, scope=request.scope)
    content: dict = {"detail": "Persistent state operation failed", "error_code": exc.code}
    if exc.code in {"registry_durability_uncertain", "registry_directory_close_failed"}:
        templates_path = request.url_for("list_templates").path
        if request.url.path == templates_path.rstrip("/") or request.url.path.startswith(templates_path):
            read_path = templates_path
        else:
            read_path = request.url_for("get_batch_history").path
        outcome = ("The change may already have been applied, but its durability could not be confirmed."
                   if exc.code == "registry_durability_uncertain" else
                   "The change was applied and synchronized, but directory descriptor cleanup failed.")
        content.update(
            detail=f"{outcome} Do not repeat the request without checking the current state. Reload {read_path} and compare before deciding what to do. Identical entries may not be attributable to this request.",
            reconcile_url=read_path,
            retryable=False,
            commit_status="uncertain" if exc.code == "registry_durability_uncertain" else "applied",
        )
    return JSONResponse(status_code=409 if isinstance(exc, TransactionTimeout) or exc.code == "bulk_revision_conflict" else 500,
                        content=content, headers={"X-Request-ID": identifier})


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    """Return an opaque 500 without logging exception contents (W-07/H-6)."""
    identifier = report_error(logger, "http_unhandled", "http.handle", exc, scope=request.scope)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"},
                        headers={"X-Request-ID": identifier})


@app.get("/batches-static/{batch_name}/{filename}")
async def serve_batch_image(batch_name: str, filename: str):
    """Serve a batch image safely (replaces the raw StaticFiles mount — W-03/K-4).

    - Validates batch_name and filename (no traversal).
    - Serves only whitelisted image extensions.
    - Sets an explicit Content-Type + `X-Content-Type-Options: nosniff`, so an
      uploaded .html/.svg can never be rendered as an active document in this origin.

    NOTE: access control for this route is delegated to the authenticating reverse
    proxy (SSO + TLS) in production — it is deliberately not bearer-gated, because
    <img> tags cannot send an Authorization header and the URL is embedded in
    exported METS/MODS XML. See docs/DEPLOYMENT.md.
    """
    try:
        validate_batch_name(batch_name)
        safe_filename = validate_filename(filename)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")

    suffix = Path(safe_filename).suffix.lower()
    content_type = _IMAGE_CONTENT_TYPES.get(suffix)
    if content_type is None:
        raise HTTPException(status_code=404, detail="Not found")

    file_path = (batches_dir / batch_name / safe_filename).resolve()
    # Anchor: the resolved path must stay inside the batches directory.
    if batches_dir.resolve() not in file_path.parents or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Not found")

    return FileResponse(
        str(file_path),
        media_type=content_type,
        headers={"X-Content-Type-Options": "nosniff"},
    )


@app.get("/")
def read_root():
    return {"message": "Welcome to the Indexcards OCR API"}
