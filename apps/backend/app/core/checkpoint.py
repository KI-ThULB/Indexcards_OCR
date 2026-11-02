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

Corrupt or unreadable files raise content-free typed errors. Missing files
raise FileNotFoundError; neither reading nor validation repairs existing data.
"""

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set, Tuple

from app.core.atomic_io import atomic_write_json

CheckpointRow = Dict[str, Any]


class CheckpointError(ValueError):
    """Content-free checkpoint failure; safe for SAR-02 diagnostics."""

    code = "checkpoint_invalid"

    def __init__(self) -> None:
        super().__init__(self.code)


class CheckpointInvalidError(CheckpointError):
    code = "checkpoint_invalid"


class CheckpointReadError(CheckpointError):
    code = "checkpoint_unreadable"


class CheckpointWriteError(CheckpointError):
    code = "checkpoint_write_failed"


def _validate_contents(results: Any, audit: Any) -> None:
    if not isinstance(results, list) or not isinstance(audit, list):
        raise CheckpointInvalidError()
    filenames: Set[str] = set()
    for row in results:
        if not isinstance(row, dict):
            raise CheckpointInvalidError()
        filename = row.get("filename")
        if (
            not isinstance(filename, str)
            or not filename.strip()
            or filename in filenames
        ):
            raise CheckpointInvalidError()
        filenames.add(filename)
        if not isinstance(row.get("success"), bool):
            raise CheckpointInvalidError()
        # Validate containers used by readers without imposing a new extraction
        # schema. Unknown fields and historical optional fields are preserved.
        for key in ("data", "edited_data", "validation", "confidence"):
            if row.get(key) is not None and not isinstance(row[key], dict):
                raise CheckpointInvalidError()
    if any(not isinstance(entry, dict) for entry in audit):
        raise CheckpointInvalidError()


def _unique_object(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    """Reject ambiguous objects without disclosing a possibly sensitive key."""
    value: Dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise CheckpointInvalidError()
        value[key] = item
    return value


def read_checkpoint(
    checkpoint_path: Path,
) -> Tuple[List[CheckpointRow], List[Dict[str, Any]]]:
    """Read both formats without repair, filtering or write-on-read.

    FileNotFoundError means absent; CheckpointInvalidError means malformed JSON
    or invalid containers/rows; CheckpointReadError means an I/O read failure.
    A legacy [] or {"results": [], "audit": []} is valid and empty. Omitted
    audit remains supported for older object checkpoints; explicit null is not.
    """
    try:
        with open(checkpoint_path, "r", encoding="utf-8") as f:
            data = json.load(f, object_pairs_hook=_unique_object)
    except FileNotFoundError:
        raise
    except (json.JSONDecodeError, UnicodeError):
        raise CheckpointInvalidError() from None
    except OSError:
        raise CheckpointReadError() from None

    if isinstance(data, list):
        results, audit = data, []
    elif isinstance(data, dict) and "results" in data:
        results, audit = data["results"], data.get("audit", [])
    else:
        raise CheckpointInvalidError()
    _validate_contents(results, audit)
    return results, audit


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
    rows, entries = list(results), list(audit)
    _validate_contents(rows, entries)
    try:
        atomic_write_json(checkpoint_path, {"results": rows, "audit": entries})
    except Exception:
        raise CheckpointWriteError() from None


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
