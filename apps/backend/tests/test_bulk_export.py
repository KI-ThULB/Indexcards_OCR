"""Consolidated CSV export: provenance, frozen schema, determinism, streaming."""
import csv
import io
import json

import pytest

from app.core.checkpoint import write_checkpoint
from app.services import bulk_export
from app.services.batch_manager import batch_manager
from app.services.bulk_manager import FOLDER_COMPLETED

FIELDS = ["Komponist", "Signatur"]


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _clean_batches():
    before = set(batch_manager.list_batches())
    yield
    for name in set(batch_manager.list_batches()) - before:
        try:
            batch_manager.delete_batch(name)
        except Exception:
            pass


def _batch_with(name: str, results: list) -> str:
    """Create a bare batch directory holding the given checkpoint results."""
    path = batch_manager.batches_dir / name
    path.mkdir(parents=True, exist_ok=True)
    write_checkpoint(path / "checkpoint.json", results, [])
    return name


def _ok(filename, komponist="Bach", signatur="Spez. 1", **kw):
    row = {
        "filename": filename,
        "batch": "b",
        "success": True,
        "duration": 2.412,
        "data": {"Komponist": komponist, "Signatur": signatur, "Datei": filename, "Batch": "b"},
        "confidence": {"Komponist": 0.92, "Signatur": 0.81},
        "confidence_overall": 0.87,
    }
    row.update(kw)
    return row


def _bad(filename, error="HTTP 500: upstream"):
    return {"filename": filename, "batch": "b", "success": False, "error": error, "duration": 1.5}


def _run(folders, schema_fields=None):
    return {
        "bulk_run_id": "7f3aaaaa-1111-4111-8111-111111111111",
        "name": "AMIGA Tonbandkartei",
        "schema_fields": schema_fields if schema_fields is not None else FIELDS,
        "folders": [
            {"source_folder": src, "batch_name": batch, "status": FOLDER_COMPLETED}
            for src, batch in folders
        ],
    }


def _rows(run) -> list:
    text = "".join(bulk_export.iter_consolidated_csv(run))
    assert text.startswith("﻿"), "UTF-8 BOM required for Excel"
    return list(csv.reader(io.StringIO(text.lstrip("﻿"))))


# --------------------------------------------------------------------------- #
# Header / schema
# --------------------------------------------------------------------------- #
def test_header_column_order():
    assert bulk_export.consolidated_header(FIELDS) == [
        "bulk_run_id", "source_folder", "source_filename", "batch_id",
        "File", "Status", "Error", "Duration(s)", "Confidence_overall",
        "Komponist_ocr", "Komponist_edited", "Komponist_confidence",
        "Signatur_ocr", "Signatur_edited", "Signatur_confidence",
    ]


def test_header_matches_documented_example():
    run = _run([("Batch_001", _batch_with("Batch_001_ab12cd34", [_ok("IMG_6662.JPG")]))])
    text = "".join(bulk_export.iter_consolidated_csv(run)).lstrip("﻿")
    header = text.split("\r\n")[0]
    assert header == (
        '"bulk_run_id","source_folder","source_filename","batch_id","File","Status",'
        '"Error","Duration(s)","Confidence_overall","Komponist_ocr","Komponist_edited",'
        '"Komponist_confidence","Signatur_ocr","Signatur_edited","Signatur_confidence"'
    )


def test_all_cells_quoted_and_crlf():
    run = _run([("Batch_001", _batch_with("B1", [_ok("a.jpg")]))])
    text = "".join(bulk_export.iter_consolidated_csv(run)).lstrip("﻿")
    assert "\r\n" in text
    for line in text.split("\r\n"):
        if line:
            assert line.startswith('"') and line.endswith('"')


def test_embedded_quotes_are_doubled():
    run = _run([("Batch_001", _batch_with("B1", [_ok("a.jpg", komponist='Bach, "JS"')]))])
    text = "".join(bulk_export.iter_consolidated_csv(run))
    assert '"Bach, ""JS"""' in text
    # And it still round-trips through a CSV reader.
    assert _rows(run)[1][9] == 'Bach, "JS"'


# --------------------------------------------------------------------------- #
# Provenance
# --------------------------------------------------------------------------- #
def test_provenance_columns_are_correct():
    b1 = _batch_with("Batch_001_ab12cd34", [_ok("IMG_6662.JPG")])
    rows = _rows(_run([("Batch_001", b1)]))
    assert rows[1][:9] == [
        "7f3aaaaa-1111-4111-8111-111111111111",
        "Batch_001",
        "IMG_6662.JPG",
        "Batch_001_ab12cd34",
        "IMG_6662.JPG",
        "success",
        "",
        "2.41",
        "87",
    ]


def test_every_row_carries_its_own_folder_provenance():
    run = _run([
        ("Batch_001", _batch_with("B1", [_ok("a.jpg")])),
        ("Batch_002", _batch_with("B2", [_ok("b.jpg")])),
    ])
    rows = _rows(run)[1:]
    assert [(r[1], r[2], r[3]) for r in rows] == [
        ("Batch_001", "a.jpg", "B1"),
        ("Batch_002", "b.jpg", "B2"),
    ]


# --------------------------------------------------------------------------- #
# Completeness
# --------------------------------------------------------------------------- #
def test_contains_all_records_across_folders():
    run = _run([
        ("Batch_001", _batch_with("B1", [_ok("a.jpg"), _ok("b.jpg")])),
        ("Batch_002", _batch_with("B2", [_ok("c.jpg"), _bad("d.jpg")])),
        ("Batch_003", _batch_with("B3", [_ok("e.jpg")])),
    ])
    rows = _rows(run)
    assert len(rows) == 1 + 5
    assert [r[2] for r in rows[1:]] == ["a.jpg", "b.jpg", "c.jpg", "d.jpg", "e.jpg"]


def test_failed_records_appear_with_status_and_error():
    run = _run([("Batch_001", _batch_with("B1", [_bad("x.jpg", "HTTP 500: boom")]))])
    row = _rows(run)[1]
    assert row[5] == "failed"
    assert row[6] == "HTTP 500: boom"
    assert row[8] == ""          # no confidence on a failure
    assert row[9] == ""          # no field values either


def test_folder_never_started_contributes_no_rows():
    run = _run([("Batch_001", _batch_with("B1", [_ok("a.jpg")]))])
    run["folders"].append({"source_folder": "Batch_002", "batch_name": None, "status": "pending"})
    assert len(_rows(run)) == 2


def test_missing_checkpoint_contributes_no_rows():
    path = batch_manager.batches_dir / "B_nocheckpoint"
    path.mkdir(parents=True, exist_ok=True)
    run = _run([("Batch_001", "B_nocheckpoint")])
    assert len(_rows(run)) == 1  # header only


# --------------------------------------------------------------------------- #
# Schema stability
# --------------------------------------------------------------------------- #
def test_missing_field_becomes_an_empty_cell_not_a_new_schema():
    """A result lacking Signatur must not shorten or reshape the row."""
    partial = _ok("a.jpg")
    del partial["data"]["Signatur"]
    del partial["confidence"]["Signatur"]

    run = _run([("Batch_001", _batch_with("B1", [partial]))])
    rows = _rows(run)
    assert len(rows[1]) == len(rows[0])
    assert rows[1][12:15] == ["", "", ""]   # Signatur triplet, all empty


def test_unexpected_extra_keys_add_no_columns():
    extra = _ok("a.jpg")
    extra["data"]["Voelligneu"] = "should not become a column"
    extra["data"]["NochEins"] = "nor this"

    run = _run([("Batch_001", _batch_with("B1", [extra]))])
    rows = _rows(run)
    assert rows[0] == bulk_export.consolidated_header(FIELDS)
    assert len(rows[1]) == len(rows[0])
    assert "Voelligneu" not in "".join(rows[0])
    assert "should not become a column" not in "".join(rows[1])


def test_internal_keys_are_not_emitted_as_columns():
    run = _run([("Batch_001", _batch_with("B1", [_ok("a.jpg")]))])
    header = _rows(run)[0]
    for internal in ("Datei", "Batch", "_entries", "_entry_count"):
        assert internal not in header


def test_frozen_schema_wins_over_the_data_on_disk():
    """Columns come from schema_fields, even if results carry other fields."""
    run = _run([("Batch_001", _batch_with("B1", [_ok("a.jpg")]))], schema_fields=["Titel"])
    rows = _rows(run)
    assert rows[0] == bulk_export.consolidated_header(["Titel"])
    assert rows[1][9:12] == ["", "", ""]     # Titel absent from the data → empty


def test_edited_values_land_in_the_edited_column():
    row = _ok("a.jpg")
    row["edited_data"] = {"Komponist": "Bach, Johann Sebastian"}
    run = _run([("Batch_001", _batch_with("B1", [row]))])
    cells = _rows(run)[1]
    assert cells[9] == "Bach"                       # _ocr keeps the raw extraction
    assert cells[10] == "Bach, Johann Sebastian"    # _edited carries the curator edit


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #
def test_rows_are_sorted_by_filename_within_a_folder():
    """A checkpoint stores results in completion order, which is not stable."""
    run = _run([("Batch_001", _batch_with("B1", [_ok("c.jpg"), _ok("a.jpg"), _ok("b.jpg")]))])
    assert [r[2] for r in _rows(run)[1:]] == ["a.jpg", "b.jpg", "c.jpg"]


def test_folders_follow_configured_order_not_alphabetical():
    run = _run([
        ("Batch_003", _batch_with("B3", [_ok("c.jpg")])),
        ("Batch_001", _batch_with("B1", [_ok("a.jpg")])),
        ("Batch_002", _batch_with("B2", [_ok("b.jpg")])),
    ])
    assert [r[1] for r in _rows(run)[1:]] == ["Batch_003", "Batch_001", "Batch_002"]


def test_export_is_byte_identical_when_re_run():
    run = _run([
        ("Batch_001", _batch_with("B1", [_ok("a.jpg"), _ok("b.jpg")])),
        ("Batch_002", _batch_with("B2", [_bad("c.jpg")])),
    ])
    first = "".join(bulk_export.iter_consolidated_csv(run))
    second = "".join(bulk_export.iter_consolidated_csv(run))
    assert first == second


def test_written_file_is_byte_identical_to_the_stream(tmp_path):
    run = _run([("Batch_001", _batch_with("B1", [_ok("a.jpg")]))])
    path = bulk_export.write_consolidated_csv(run, tmp_path / "consolidated.csv")
    # Compare bytes: read_text() would translate CRLF away and hide a newline bug.
    expected = "".join(bulk_export.iter_consolidated_csv(run)).encode("utf-8")
    assert path.read_bytes() == expected
    assert b"\r\n" in path.read_bytes()
    assert {p.name for p in tmp_path.iterdir()} == {"consolidated.csv"}


# --------------------------------------------------------------------------- #
# Multi-entry expansion (Findmittel)
# --------------------------------------------------------------------------- #
def test_multi_entry_card_expands_to_one_row_per_entry():
    entries = [
        {"Komponist": "Bach", "Signatur": "S1"},
        {"Komponist": "Handel", "Signatur": "S2"},
        {"Komponist": "Telemann", "Signatur": "S3"},
    ]
    result = {
        "filename": "page.jpg",
        "batch": "b",
        "success": True,
        "duration": 3.0,
        "data": {"_entries": json.dumps(entries), "_entry_count": "3",
                 "Datei": "page.jpg", "Batch": "b"},
    }
    run = _run([("Batch_001", _batch_with("B1", [result]))])
    rows = _rows(run)[1:]

    assert len(rows) == 3
    assert [r[9] for r in rows] == ["Bach", "Handel", "Telemann"]
    # Provenance repeats on every entry row, so each stays traceable.
    assert all(r[1:5] == ["Batch_001", "page.jpg", "B1", "page.jpg"] for r in rows)
    # Confidence is per page in v1 → blank on entry rows.
    assert all(r[8] == "" and r[11] == "" for r in rows)


def test_corrupt_entries_blob_falls_back_to_a_single_row():
    result = _ok("page.jpg")
    result["data"]["_entries"] = "{not json"
    run = _run([("Batch_001", _batch_with("B1", [result]))])
    assert len(_rows(run)) == 2


def test_row_counts_matches_the_generated_csv():
    run = _run([
        ("Batch_001", _batch_with("B1", [
            _ok("a.jpg"),
            {"filename": "p.jpg", "batch": "b", "success": True, "duration": 1.0,
             "data": {"_entries": json.dumps([{"Komponist": "X"}, {"Komponist": "Y"}])}},
        ])),
        ("Batch_002", _batch_with("B2", [_bad("z.jpg")])),
    ])
    rows, failures = bulk_export.row_counts(run)
    assert rows == len(_rows(run)) - 1 == 4
    assert failures == 1


# --------------------------------------------------------------------------- #
# Failures CSV
# --------------------------------------------------------------------------- #
def test_failures_csv_lists_only_failures_with_provenance():
    run = _run([
        ("Batch_001", _batch_with("B1", [_ok("a.jpg"), _bad("b.jpg", "HTTP 500")])),
        ("Batch_002", _batch_with("B2", [_bad("c.jpg", "Timeout")])),
    ])
    text = "".join(bulk_export.iter_failures_csv(run))
    assert text.startswith("﻿")
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))

    assert rows[0] == bulk_export.FAILURE_COLUMNS
    assert [(r[1], r[2], r[5]) for r in rows[1:]] == [
        ("Batch_001", "b.jpg", "HTTP 500"),
        ("Batch_002", "c.jpg", "Timeout"),
    ]


def test_failures_csv_is_header_only_when_nothing_failed():
    run = _run([("Batch_001", _batch_with("B1", [_ok("a.jpg")]))])
    rows = list(csv.reader(io.StringIO(
        "".join(bulk_export.iter_failures_csv(run)).lstrip("﻿")
    )))
    assert len(rows) == 1


# --------------------------------------------------------------------------- #
# Streaming — bounded memory
# --------------------------------------------------------------------------- #
def test_only_one_checkpoint_is_read_at_a_time(monkeypatch):
    """The generator must not pre-load every folder's results."""
    run = _run([
        ("Batch_001", _batch_with("B1", [_ok("a.jpg")])),
        ("Batch_002", _batch_with("B2", [_ok("b.jpg")])),
        ("Batch_003", _batch_with("B3", [_ok("c.jpg")])),
    ])
    opened: list = []
    real = bulk_export._folder_results
    monkeypatch.setattr(
        bulk_export, "_folder_results",
        lambda name: (opened.append(name), real(name))[1],
    )

    stream = bulk_export.iter_consolidated_csv(run)
    next(stream)   # BOM
    next(stream)   # header
    assert opened == []
    next(stream)   # first data row
    assert opened == ["B1"], "later folders must not be read yet"
    list(stream)
    assert opened == ["B1", "B2", "B3"]
