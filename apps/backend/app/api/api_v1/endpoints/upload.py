import logging
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import validate_filename, validate_session_id
from app.models.schemas import UploadResponse
from app.services.batch_manager import batch_manager

logger = logging.getLogger(__name__)

router = APIRouter()

# 8 KiB streaming chunk — small enough to abort oversized uploads early (H-1).
_CHUNK = 8192


def _sniff_image_type(head: bytes) -> Optional[str]:
    """Detect image type from magic bytes (imghdr was removed in Python 3.13+).
    Returns 'jpeg' | 'png' | 'tiff' | None. Rejects HTML/SVG/scripts (W-03)."""
    if head[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    return None


def _looks_like_allowed_image(head: bytes, suffix: str) -> bool:
    """True when the magic-byte type matches the (already-whitelisted) extension."""
    kind = _sniff_image_type(head)
    if kind == "jpeg" and suffix in {".jpg", ".jpeg"}:
        return True
    if kind == "png" and suffix == ".png":
        return True
    if kind == "tiff" and suffix in {".tif", ".tiff"}:
        return True
    return False


@router.post("/", response_model=UploadResponse)
@limiter.limit(settings.RATE_LIMIT_UPLOAD)
async def upload_files(
    request: Request,
    files: List[UploadFile] = File(...),
    session_id: Optional[str] = Form(None),
):
    """
    Upload multiple images to a temporary session.
    If session_id is not provided, a new one is generated.
    Rejects traversal in session_id, non-image content, oversized and over-count uploads.
    Returns session_id and filenames.
    """
    if not session_id:
        session_id = batch_manager.generate_session_id()
    else:
        try:
            validate_session_id(session_id)  # reject ../ traversal (W-02)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid session id")

    if len(files) > settings.MAX_UPLOAD_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"Too many files (max {settings.MAX_UPLOAD_FILES})",
        )

    allowed_ext = settings.allowed_image_extensions
    temp_session_path = batch_manager.get_temp_session_path(session_id)
    filenames: list[str] = []

    for file in files:
        raw_name = file.filename or f"unnamed_{len(filenames)}"
        # Sanitize the filename: strip any directory part and whitelist chars (H-1).
        bare = Path(raw_name).name
        suffix = Path(bare).suffix.lower()
        if suffix not in allowed_ext:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type '{suffix}'. Allowed: {sorted(allowed_ext)}",
            )
        try:
            safe_name = validate_filename(bare)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid filename: {raw_name!r}")

        file_path = temp_session_path / safe_name

        # Stream to disk with a running byte count; abort past the size limit.
        total = 0
        first_chunk = b""
        with file_path.open("wb") as buffer:
            while True:
                chunk = await file.read(_CHUNK)
                if not chunk:
                    break
                if not first_chunk:
                    first_chunk = chunk[:32]
                total += len(chunk)
                if total > settings.MAX_UPLOAD_BYTES:
                    buffer.close()
                    file_path.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=400,
                        detail=f"File '{safe_name}' exceeds {settings.MAX_UPLOAD_BYTES} bytes",
                    )
                buffer.write(chunk)

        # Magic-byte check: content must actually be an allowed image type (W-03).
        if not _looks_like_allowed_image(first_chunk, suffix):
            file_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=400,
                detail=f"File '{safe_name}' is not a valid image",
            )

        filenames.append(safe_name)

    return UploadResponse(
        session_id=session_id,
        filenames=filenames,
        message=f"Successfully uploaded {len(filenames)} files.",
    )


@router.delete("/{session_id}", status_code=204)
async def delete_session(session_id: str):
    """Delete a temp upload session and its files."""
    try:
        validate_session_id(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session id")
    deleted = batch_manager.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    return None
