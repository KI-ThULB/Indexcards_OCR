"""Consolidated, provenance-bearing CSV export for a bulk run.

14,000 rows must not be assembled in the browser or held in backend memory, so
the export is generated server-side and **streamed**: folders are visited in the
run's configured order and each folder's ``checkpoint.json`` is read, emitted and
released before the next is opened. Peak memory is one batch, whatever the
collection size. Per-batch results and the existing per-batch exports are
untouched and remain available.

Schema stability
----------------
Columns come from ``schema_fields``, frozen in ``run.json`` when the run was
created, so editing the template mid-run cannot shift columns. A result that is
*missing* a field writes an empty cell; a result carrying *unexpected extra*
keys contributes no new columns — the extras are counted and logged so drift is
visible without the CSV shape ever changing. Internal keys (``_entries``,
``_entry_count``, ``Datei``, ``Batch``) are handled explicitly and never emitted
as data columns.

Format parity
-------------
Byte-for-byte conventions of the existing client-side exporter
(``apps/frontend/src/features/results/useResultsExport.ts``): UTF-8 BOM so Excel
opens it correctly, CRLF line endings, every cell quoted with ``"`` doubled, and
an ``_ocr`` / ``_edited`` / ``_confidence`` triplet per field. Multi-entry cards
(``data["_entries"]``, the Findmittel case) expand to one row per entry, matching
``expandResults.ts``; confidence is per-page in v1, so entry rows leave it blank.

Determinism
-----------
Folders in configured processing order, rows within a folder sorted by filename
(a checkpoint stores results in *completion* order, which is not stable, so the
sort is explicit). No timestamps are written. Re-running the export over the same
state therefore produces a byte-identical file.
"""
import csv
import io
import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from app.core.atomic_io import atomic_write_chunks
from app.core.checkpoint import read_checkpoint
from app.services.batch_manager import batch_manager
from app.services.validation import groups as group_util

logger = logging.getLogger(__name__)

# Provenance columns — what makes a consolidated row traceable back to the scan.
PROVENANCE_COLUMNS = ["bulk_run_id", "source_folder", "source_filename", "batch_id"]
# Per-record columns, mirroring the client-side CSV exporter.
RECORD_COLUMNS = ["File", "Status", "Error", "Duration(s)", "Confidence_overall"]
# Engine-internal keys that live in `data` but are never data columns.
INTERNAL_DATA_KEYS = frozenset({"_entries", "_entry_count", "Datei", "Batch"})

FAILURE_COLUMNS = PROVENANCE_COLUMNS + ["File", "Error", "Duration(s)"]

# UTF-8 BOM. Excel needs it to open the file as UTF-8; the client-side exporter
# prepends the same character.
BOM = "\ufeff"


def group_columns(label: str, definition: Any) -> List[str]:
    """Deterministic columns for one repeatable group, expanded in field position.

    ``<G>_count`` carries the real number of entries even when it exceeds the
    frozen width, and ``<G>_overflow_json`` preserves the surplus verbatim — so a
    card with more entries than ``max_items`` is never silently truncated.
    """
    children = group_util.child_names(definition)
    limit = group_util.max_items(definition)
    columns = [f"{label}_count"]
    for index in range(1, limit + 1):
        for child in children:
            base = f"{label}_{index}_{child}"
            columns += [f"{base}_ocr", f"{base}_edited", f"{base}_confidence"]
    columns.append(f"{label}_overflow_json")
    return columns


def consolidated_header(
    schema_fields: List[str], field_groups: Optional[Dict[str, Any]] = None
) -> List[str]:
    """The frozen column order for a run's consolidated CSV.

    A repeatable group expands **in place** at its position in the field list, so
    the column order stays template-driven and deterministic.
    """
    groups = field_groups or {}
    header = list(PROVENANCE_COLUMNS) + list(RECORD_COLUMNS)
    for field in schema_fields:
        definition = groups.get(field)
        if definition is not None and group_util.child_names(definition):
            header += group_columns(field, definition)
        else:
            header += [f"{field}_ocr", f"{field}_edited", f"{field}_confidence"]
    return header


def _pct(value: Any) -> str:
    """Confidence as a whole percentage, or an empty cell. Mirrors the frontend."""
    if value is None:
        return ""
    try:
        return str(round(float(value) * 100))
    except (TypeError, ValueError):
        return ""


def _duration(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return ""


class _RowWriter:
    """Formats one CSV row at a time, so nothing accumulates in memory."""

    def __init__(self) -> None:
        self._buf = io.StringIO()
        # QUOTE_ALL + doublequote and CRLF match the client-side exporter exactly.
        self._writer = csv.writer(
            self._buf, quoting=csv.QUOTE_ALL, doublequote=True, lineterminator="\r\n"
        )

    def row(self, values: List[str]) -> str:
        self._writer.writerow(values)
        out = self._buf.getvalue()
        self._buf.seek(0)
        self._buf.truncate(0)
        return out


def _folder_results(batch_name: Optional[str]) -> List[Dict[str, Any]]:
    """One folder's results, sorted by filename for a deterministic row order."""
    if not batch_name:
        return []
    try:
        checkpoint = batch_manager.get_batch_path(batch_name) / "checkpoint.json"
    except ValueError:
        logger.warning("Skipping folder with invalid batch name %r during export", batch_name)
        return []
    if not checkpoint.exists():
        return []
    try:
        results, _ = read_checkpoint(checkpoint)
    except Exception:
        logger.exception("Could not read checkpoint for %s during export", batch_name)
        return []
    return sorted(results, key=lambda r: str(r.get("filename", "")))


def _entry_rows(
    result: Dict[str, Any],
    schema_fields: List[str],
    prefix: List[str],
    group_defs: Optional[Dict[str, Any]] = None,
) -> Optional[List[List[str]]]:
    """Expand a multi-entry card into one row per entry, or None if not one.

    Mirrors expandResults.ts: entries come from the ``_entries`` JSON blob.
    Confidence is per-page in v1, so entry rows leave both confidence cells
    blank, as the client-side exporter does.
    """
    data = result.get("data") or {}
    entries_json = data.get("_entries")
    if result.get("success") is not True or not entries_json:
        return None
    try:
        entries = json.loads(entries_json)
    except (TypeError, ValueError):
        return None  # fall through to single-row handling, like the frontend
    if not isinstance(entries, list):
        return None

    rows: List[List[str]] = []
    for entry in entries:
        entry = entry if isinstance(entry, dict) else {}
        row = list(prefix) + [
            str(result.get("filename", "")),
            "success",
            str(result.get("error") or ""),
            _duration(result.get("duration")),
            "",  # Confidence_overall — per page, not per entry
        ]
        for field in schema_fields:
            definition = (group_defs or {}).get(field)
            if definition is not None and group_util.child_names(definition):
                # A multi-entry (_entries) card and a repeatable group do not
                # co-occur in practice; keep the column width correct by writing
                # the group's cells empty rather than shifting later columns.
                row += [""] * len(group_columns(field, definition))
                continue
            row += [str(entry.get(field, "") or ""), "", ""]
        rows.append(row)
    return rows


def _group_cells(
    result: Dict[str, Any], label: str, definition: Any
) -> List[str]:
    """Cells for one repeatable group on one card.

    ``_ocr`` reads the model's own array and ``_edited`` the curator's, both
    positionally; ``_confidence`` uses the flattened key for that position, which
    aligns with the model's array. ``_count`` and the overflow reflect what the
    curator currently sees (edited if present, else raw).
    """
    children = group_util.child_names(definition)
    limit = group_util.max_items(definition)
    confidence = result.get("confidence") or {}

    raw_items = group_util.parse_group((result.get("data") or {}).get(label))
    edited_items = group_util.parse_group((result.get("edited_data") or {}).get(label))
    effective = group_util.effective_items(result, label)

    cells = [str(len(effective))]
    for index in range(limit):
        for child in children:
            raw = raw_items[index].get(child, "") if index < len(raw_items) else ""
            edit = edited_items[index].get(child, "") if index < len(edited_items) else ""
            conf = (
                confidence.get(group_util.child_key(label, index, child))
                if isinstance(confidence, dict) else None
            )
            cells += [str(raw or ""), str(edit or ""), _pct(conf)]

    # Entries beyond the frozen width are preserved verbatim, never dropped.
    overflow = effective[limit:]
    cells.append(group_util.serialise_group(overflow) if overflow else "")
    return cells


def _single_row(
    result: Dict[str, Any],
    schema_fields: List[str],
    prefix: List[str],
    field_groups: Optional[Dict[str, Any]] = None,
) -> List[str]:
    groups = field_groups or {}
    data = result.get("data") or {}
    edited = result.get("edited_data") or {}
    confidence = result.get("confidence") or {}

    row = list(prefix) + [
        str(result.get("filename", "")),
        "success" if result.get("success") is True else "failed",
        str(result.get("error") or ""),
        _duration(result.get("duration")),
        _pct(result.get("confidence_overall")),
    ]
    for field in schema_fields:
        definition = groups.get(field)
        if definition is not None and group_util.child_names(definition):
            row += _group_cells(result, field, definition)
            continue
        # A missing field writes an empty cell — never a changed schema.
        row += [
            str(data.get(field, "") or ""),
            str(edited.get(field, "") or ""),
            _pct(confidence.get(field) if isinstance(confidence, dict) else None),
        ]
    return row


def _count_unexpected_keys(result: Dict[str, Any], known: frozenset) -> int:
    data = result.get("data") or {}
    if not isinstance(data, dict):
        return 0
    return sum(1 for k in data if k not in known and k not in INTERNAL_DATA_KEYS)


def iter_consolidated_csv(run: Dict[str, Any]) -> Iterator[str]:
    """Yield the consolidated CSV chunk by chunk (header first, then rows).

    One folder's checkpoint is in memory at a time.
    """
    schema_fields = list(run.get("schema_fields", []))
    field_groups = run.get("field_groups") or {}
    # Group labels are schema, not stray data: their children must not be counted
    # as unexpected keys, and the group label itself is a legitimate field.
    known = frozenset(schema_fields) | {
        child for definition in field_groups.values()
        for child in group_util.child_names(definition)
    }
    writer = _RowWriter()
    bulk_run_id = str(run.get("bulk_run_id", ""))

    # UTF-8 BOM so Excel opens the file in the right encoding.
    yield BOM
    yield writer.row(consolidated_header(schema_fields, field_groups))

    unexpected = 0
    emitted = 0
    for folder in run.get("folders", []):
        source_folder = str(folder.get("source_folder", ""))
        batch_name = folder.get("batch_name")
        for result in _folder_results(batch_name):
            prefix = [
                bulk_run_id,
                source_folder,
                str(result.get("filename", "")),
                str(batch_name or ""),
            ]
            unexpected += _count_unexpected_keys(result, known)
            rows = _entry_rows(result, schema_fields, prefix, field_groups)
            if rows is None:
                rows = [_single_row(result, schema_fields, prefix, field_groups)]
            for row in rows:
                emitted += 1
                yield writer.row(row)

    if unexpected:
        # Visible without ever changing the CSV shape. Counts only — never the
        # key names or values, which could carry extracted metadata.
        logger.info(
            "Bulk export %s: dropped %d unexpected data key(s) not in the frozen schema",
            bulk_run_id, unexpected,
        )
    logger.info("Bulk export %s: wrote %d row(s)", bulk_run_id, emitted)


def iter_failures_csv(run: Dict[str, Any]) -> Iterator[str]:
    """Yield a CSV of failed image records, so they can be retried selectively
    without rerunning the collection."""
    writer = _RowWriter()
    bulk_run_id = str(run.get("bulk_run_id", ""))

    yield BOM
    yield writer.row(FAILURE_COLUMNS)

    for folder in run.get("folders", []):
        source_folder = str(folder.get("source_folder", ""))
        batch_name = folder.get("batch_name")
        for result in _folder_results(batch_name):
            if result.get("success") is True:
                continue
            yield writer.row([
                bulk_run_id,
                source_folder,
                str(result.get("filename", "")),
                str(batch_name or ""),
                str(result.get("filename", "")),
                str(result.get("error") or ""),
                _duration(result.get("duration")),
            ])


def row_counts(run: Dict[str, Any]) -> Tuple[int, int]:
    """(consolidated rows, failed records) without materialising the CSV."""
    schema_fields = list(run.get("schema_fields", []))
    field_groups = run.get("field_groups") or {}
    rows = 0
    failures = 0
    for folder in run.get("folders", []):
        for result in _folder_results(folder.get("batch_name")):
            if result.get("success") is not True:
                failures += 1
            entry_rows = _entry_rows(result, schema_fields, [], field_groups)
            rows += len(entry_rows) if entry_rows is not None else 1
    return rows, failures


def write_consolidated_csv(run: Dict[str, Any], path: Path) -> Path:
    """Generate the consolidated CSV to *path* atomically, streaming as it goes."""
    atomic_write_chunks(path, iter_consolidated_csv(run))
    return path
