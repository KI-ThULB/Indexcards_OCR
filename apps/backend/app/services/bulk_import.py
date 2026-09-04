"""Server-side ingestion of source folders from ``BULK_IMPORT_ROOT``.

~14,000 scans must not traverse the browser, so a bulk run reads its images
straight off a filesystem the backend can see. That is the only new ingestion
path; the HTTP upload flow is untouched and its validation is unchanged.

Security model
--------------
* The feature is **off** unless ``BULK_IMPORT_ROOT`` names an existing
  directory. While off, nothing here is reachable.
* Only the root's **immediate** subfolders are ever exposed (no recursion in v1).
* **Folder names are never trusted as paths.** The client picks a *name* from
  the listing; :func:`resolve_source_folder` re-resolves it with the existing
  ``safe_join`` against the root and re-validates it against the live listing.
  Anything that escapes the root is rejected. A symlinked subfolder pointing
  outside the root is rejected too, because ``safe_join`` resolves before
  comparing.
* Symlinked *files* inside a source folder are skipped rather than imported, so
  a link planted in the import root cannot pull an arbitrary file into a batch
  directory (from which ``/batches-static/`` would serve it).
* Supported extensions are enforced independently of upload validation, via the
  shared ``is_supported_image`` — which also gives case-insensitive ``.JPG`` /
  ``.JPEG`` / ``.TIFF`` matching, a hard requirement for these collections.

Immutability of the source files
--------------------------------
Import mode ``hardlink`` (the default) creates a second directory entry for the
*same inode*. That is what makes importing 28x500 scans free of extra disk use,
and it is why **any in-place write to a batch-side image would silently corrupt
the archival original**. Symlinks are not an option: ``serve_batch_image``
resolves the path and requires the result to stay inside ``BATCHES_DIR``, so a
symlinked image would 404.

Permitted on the batch-side link: moving it (into ``_errors/`` on failure and
back on retry), renaming it, deleting it (delete/purge/retention/rmtree).
Forbidden anywhere: opening an image for writing, truncating it, or writing a
derived image over it.

The pipeline was audited against this rule and satisfies it as written:
``ocr_engine._encode_image_to_base64`` resizes into an in-memory ``BytesIO``
(``img.save(buf, …)``, never a path); ``serve_batch_image`` uses a read-only
``FileResponse``; every image-level ``shutil`` call is a ``move`` or an
``rmtree``. Keep it that way — see ``tests/test_bulk_immutability.py``, which
asserts byte-identity of every source file after success, failure, retry and
purge.
"""
import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.images import is_supported_image, iter_image_files
from app.core.security import safe_join, validate_filename
from app.services.batch_manager import batch_manager

logger = logging.getLogger(__name__)

IMPORT_MODE_HARDLINK = "hardlink"
IMPORT_MODE_COPY = "copy"


class BulkImportError(Exception):
    """A source folder could not be read or materialised as a batch."""


class BulkImportDisabled(BulkImportError):
    """Bulk mode is not configured (``BULK_IMPORT_ROOT`` empty or missing)."""


def is_enabled() -> bool:
    """True only when an import root is configured and exists."""
    return settings.bulk_enabled


def import_root() -> Path:
    """The configured import root, resolved. Raises when bulk mode is off."""
    if not is_enabled():
        raise BulkImportDisabled("Bulk import is not configured")
    return Path(settings.BULK_IMPORT_ROOT).expanduser().resolve()


def source_images(folder: Path) -> List[Path]:
    """Supported, sorted, non-symlink image files directly inside *folder*.

    One helper for both counting and importing, so the count a curator reviews
    is exactly the set of files that will be processed. Sorted by
    ``iter_image_files``, which is what makes row order deterministic.
    """
    return [p for p in iter_image_files(folder) if not p.is_symlink()]


def list_source_folders() -> Dict[str, Any]:
    """List the import root's immediate subfolders with their image counts.

    Capped at ``BULK_MAX_FOLDERS`` so a pathological root cannot stall the API;
    the response says whether the listing was truncated.
    """
    root = import_root()
    names = sorted(
        entry.name
        for entry in root.iterdir()
        if entry.is_dir() and not entry.is_symlink() and not entry.name.startswith(".")
    )
    truncated = len(names) > settings.BULK_MAX_FOLDERS
    folders: List[Dict[str, Any]] = []
    for name in names[: settings.BULK_MAX_FOLDERS]:
        try:
            count = len(source_images(root / name))
        except OSError:
            logger.warning("Could not read source folder %r", name)
            continue
        folders.append({"name": name, "images_total": count})
    return {"root_configured": True, "folders": folders, "truncated": truncated}


def _require_single_component(name: str) -> str:
    """Reject anything that is not exactly one clean path component.

    Note this is deliberately stricter than ``validate_filename``, which *strips*
    a directory part before validating (its documented defence-in-depth
    behaviour). Stripping would silently turn ``../amiga/Batch_001`` into
    ``Batch_001`` and import it. A folder name that is not already a bare name
    did not come from our listing, so it is refused outright rather than
    reinterpreted.
    """
    if not name or name in (".", "..") or name.startswith(".."):
        raise BulkImportError(f"Invalid source folder: {name!r}")
    if any(ch in name for ch in ("/", "\\", "\x00")):
        raise BulkImportError(f"Invalid source folder: {name!r}")
    if name != Path(name).name:
        raise BulkImportError(f"Invalid source folder: {name!r}")
    return name


def resolve_source_folder(name: str) -> Path:
    """Resolve a client-supplied folder *name* to a directory inside the root.

    Defence in depth, in this order: the name must be a single clean component,
    it must still appear in the **live listing** (so hidden folders, symlinked
    folders and folders that vanished are all refused), and ``safe_join`` must
    confirm the resolved path stays inside the root. Raises
    :class:`BulkImportError` otherwise — never a partial or reinterpreted path.
    """
    root = import_root()
    _require_single_component(name)
    try:
        validate_filename(name)
    except ValueError as e:
        raise BulkImportError(f"Invalid source folder: {name!r}") from e

    # Re-validate against what the root actually offers right now, using the
    # same listing the client chose from.
    offered = {f["name"] for f in list_source_folders()["folders"]}
    if name not in offered:
        raise BulkImportError(f"Source folder not found: {name!r}")

    try:
        candidate = safe_join(root, name)
    except ValueError as e:
        raise BulkImportError(f"Source folder escapes the import root: {name!r}") from e
    if not candidate.is_dir() or candidate.is_symlink() or candidate.parent != root:
        raise BulkImportError(f"Source folder not found: {name!r}")
    return candidate


def _link_or_copy(src: Path, dst: Path, mode: str) -> str:
    """Materialise *src* at *dst*. Returns the mode actually used.

    Hardlink first (no extra disk), falling back to a copy per file when the
    link cannot be made — typically ``EXDEV`` (source on another filesystem) or
    a filesystem without hardlink support. Either way *src* is only ever read.
    """
    if mode == IMPORT_MODE_HARDLINK:
        try:
            os.link(src, dst)
            return IMPORT_MODE_HARDLINK
        except OSError as e:
            logger.info("Hardlink failed for %s (%s) — copying instead", src.name, e)
    shutil.copy2(src, dst)
    return IMPORT_MODE_COPY


def materialise_folder(
    source_folder: str,
    *,
    fields: List[str],
    prompt_template: Optional[str] = None,
    field_rules: Optional[Dict[str, Any]] = None,
    authority_bindings: Optional[Dict[str, Any]] = None,
    describe_pictures: bool = False,
    field_groups: Optional[Dict[str, Any]] = None,
    mode: Optional[str] = None,
) -> Dict[str, Any]:
    """Register one source folder as an ordinary batch and return its details.

    The batch is created through the existing ``batch_manager.create_batch``, so
    it appears in ``batches.json``, gets a uuid-suffixed sanitised directory
    name, is served, purged and retained exactly like an uploaded batch, and
    carries the run's template in its own ``config.json``.

    Images are staged into a temp upload session and then moved into the batch
    directory by ``create_batch``. Temp and batch directories both live under
    ``DATA_DIR``, so that move is a rename: a hardlink keeps its inode and
    therefore stays a link to the archival original.

    Returns ``{"batch_name", "images_total", "mode"}``. Raises
    :class:`BulkImportError` when the folder is unreadable or holds no
    supported images (a configuration fault the caller reports as structural).
    """
    resolved_mode = (mode or settings.BULK_IMPORT_MODE or IMPORT_MODE_HARDLINK).strip().lower()
    if resolved_mode not in (IMPORT_MODE_HARDLINK, IMPORT_MODE_COPY):
        raise BulkImportError(f"Unsupported BULK_IMPORT_MODE: {resolved_mode!r}")

    src_dir = resolve_source_folder(source_folder)
    try:
        images = source_images(src_dir)
    except OSError as e:
        raise BulkImportError(f"Cannot read source folder {source_folder!r}: {e}") from e
    if not images:
        raise BulkImportError(f"Source folder {source_folder!r} contains no supported images")

    session_id = str(uuid.uuid4())
    session_dir = batch_manager.get_temp_session_path(session_id)
    modes_used: set = set()
    try:
        for image in images:
            # Independent extension check — bulk import bypasses HTTP upload
            # validation entirely, so it must enforce this itself.
            if not is_supported_image(image):
                continue
            modes_used.add(_link_or_copy(image, session_dir / image.name, resolved_mode))

        batch_name = batch_manager.create_batch(
            custom_name=source_folder,
            session_id=session_id,
            fields=fields,
            prompt_template=prompt_template,
            field_rules=field_rules,
            authority_bindings=authority_bindings,
            field_groups=field_groups,
            describe_pictures=describe_pictures,
        )
    except Exception:
        # Never leave a half-staged session behind. Removing staged hardlinks
        # deletes only the batch-side directory entries; the source files are
        # untouched.
        try:
            batch_manager.delete_session(session_id)
        except Exception:
            logger.warning("Could not clean up temp session %s", session_id)
        raise

    batch_path = batch_manager.get_batch_path(batch_name)
    return {
        "batch_name": batch_name,
        "images_total": len(source_images(batch_path)),
        "mode": IMPORT_MODE_COPY if IMPORT_MODE_COPY in modes_used else resolved_mode,
    }
