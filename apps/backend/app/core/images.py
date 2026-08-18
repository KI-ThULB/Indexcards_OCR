"""Central helper for supported-image detection.

One canonical source of truth (``settings.allowed_image_extensions``) and one
case-insensitive comparison, shared by upload validation, batch processing and
enumeration. This guarantees a file accepted at upload cannot later be dropped
by processing purely because of filename casing (e.g. ``IMG_6662.JPG``), and
keeps behaviour identical on case-sensitive (Linux) and case-insensitive
(macOS/Windows) filesystems.
"""
from pathlib import Path
from typing import List, Union

from app.core.config import settings


def is_supported_image(path: Union[str, Path]) -> bool:
    """True if *path*'s extension is a supported image type, ignoring case.

    The suffix is normalised with ``.lower()`` before comparison against the
    canonical extension set, so ``.JPG``, ``.JpG`` and ``.jpg`` all match.
    """
    return Path(path).suffix.lower() in settings.allowed_image_extensions


def iter_image_files(directory: Path) -> List[Path]:
    """Return the directory's supported image files, sorted, matched case-insensitively.

    Only regular files are considered; sub-directories (``_errors/``) and
    sidecar files (``checkpoint.json``) are skipped.
    """
    return sorted(
        f for f in directory.iterdir() if f.is_file() and is_supported_image(f)
    )
