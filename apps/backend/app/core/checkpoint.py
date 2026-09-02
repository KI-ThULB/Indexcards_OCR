"""Canonical reader/writer for a batch's ``checkpoint.json``.

Two writers used to disagree on the on-disk shape. The OCR engine wrote a bare
list of result rows; the results API wrote ``{"results": [...], "audit": [...]}``
*and* migrated a legacy list into that object shape on read. So merely opening
the Results step (``GET /batches/{name}/results``) rewrote the file into a shape
the engine's resume loop could not iterate: it walked the dict's keys, appended
the string ``"results"`` to its result list, and a later
``{r["filename"]: r for r in results}`` raised ``TypeError``, which
``run_ocr_task`` turned into a **failed** batch. Net effect: view a batch's
results once and resume/retry for that batch was broken.

This module is the single definition of the format for both sides:

* :func:`read_checkpoint` accepts **both** shapes and normalises them to one
  canonical ``(results, audit)`` tuple. It is **pure** — reading never writes,
  so opening the Results step can no longer change what a later resume sees. A
  legacy file is upgraded on the next real write instead, so callers must not
  depend on read-triggered migration.
* :func:`write_checkpoint` always writes the object shape, **atomically**
  (temp file in the same directory + ``os.replace``), so a reboot 400 images
  into a folder cannot leave a truncated checkpoint behind.
* :func:`completed_filenames` is the single definition of "already done",
  shared by single-batch resume and bulk resume.

Corrupt or unreadable JSON raises, so each caller decides how to react (the
engine logs and starts fresh; endpoints surface a 500).
"""
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set, Tuple

CheckpointRow = Dict[str, Any]


def _coerce_rows(value: Any) -> List[CheckpointRow]:
    """Keep only dict rows. A non-dict entry carries no usable record and would
    crash every consumer (``row["filename"]``) — exactly the failure this module
    exists to prevent."""
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def read_checkpoint(checkpoint_path: Path) -> Tuple[List[CheckpointRow], List[Dict[str, Any]]]:
    """Read ``checkpoint.json`` and return ``(results, audit)``.

    Accepts both the legacy flat array and the current
    ``{"results": [...], "audit": [...]}`` object. Never writes.

    Raises ``json.JSONDecodeError`` / ``OSError`` on an unreadable or corrupt
    file, and ``ValueError`` if the top-level JSON is neither list nor object.
    """
    with open(checkpoint_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        # Legacy flat-array format — normalise, but leave the file untouched.
        return _coerce_rows(data), []
    if isinstance(data, dict):
        return _coerce_rows(data.get("results")), list(data.get("audit") or [])
    raise ValueError(f"Unsupported checkpoint format in {checkpoint_path}: {type(data).__name__}")


def write_checkpoint(
    checkpoint_path: Path,
    results: Iterable[CheckpointRow],
    audit: Iterable[Dict[str, Any]],
) -> None:
    """Atomically write ``{"results": …, "audit": …}`` to *checkpoint_path*.

    The payload is written to a temp file in the same directory, flushed and
    fsynced, then moved into place with ``os.replace`` (atomic on POSIX and
    Windows). A crash mid-write therefore leaves the previous checkpoint intact
    rather than a truncated file.
    """
    path = Path(checkpoint_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"results": list(results), "audit": list(audit)}

    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, str(path))
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def completed_filenames(results: Iterable[CheckpointRow]) -> Set[str]:
    """Filenames that already succeeded — the single definition of "already done".

    Used by both single-batch resume and bulk resume so a card that has been
    extracted is never sent to the model a second time.
    """
    return {
        str(row["filename"])
        for row in results
        if isinstance(row, dict) and row.get("success") is True and row.get("filename")
    }
