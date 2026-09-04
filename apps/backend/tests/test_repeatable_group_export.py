"""CSV export of repeatable groups: one row per card, deterministic, lossless."""
import csv
import io
import json

import pytest

from app.core.checkpoint import write_checkpoint
from app.services import bulk_export
from app.services.batch_manager import batch_manager
from app.services.validation import groups as G

CHILDREN = ["Lfd_Nr", "Titel", "Spieldauer"]
TRACKS_20 = {"max_items": 20, "fields": [{"name": c} for c in CHILDREN]}
TRACKS_2 = {"max_items": 2, "fields": [{"name": c} for c in CHILDREN]}
FIELDS = ["Gesamttitel", "Titel_Tracks", "Gesamtspieldauer"]


@pytest.fixture(autouse=True)
def _clean():
    before = set(batch_manager.list_batches())
    yield
    for name in set(batch_manager.list_batches()) - before:
        try:
            batch_manager.delete_batch(name)
        except Exception:
            pass


def _batch(name, results):
    path = batch_manager.batches_dir / name
    path.mkdir(parents=True, exist_ok=True)
    write_checkpoint(path / "checkpoint.json", results, [])
    return name


def _card(items, *, edited=None, confidence=None, gesamt="Gershwin - Evergreens",
          dauer="10'15", filename="card.jpg"):
    row = {
        "filename": filename, "batch": "b", "success": True, "duration": 1.0,
        "data": {"Gesamttitel": gesamt, "Titel_Tracks": G.serialise_group(items),
                 "Gesamtspieldauer": dauer, "Datei": filename, "Batch": "b"},
    }
    if edited is not None:
        row["edited_data"] = {"Titel_Tracks": G.serialise_group(edited)}
    if confidence:
        row["confidence"] = confidence
    return row


def _run(results, groups=TRACKS_20, fields=None):
    return {
        "bulk_run_id": "run-1", "schema_fields": fields or FIELDS,
        "field_groups": {"Titel_Tracks": groups} if groups else None,
        "folders": [{"source_folder": "Batch_001",
                     "batch_name": _batch("B1", results), "status": "completed"}],
    }


def _rows(run):
    text = "".join(bulk_export.iter_consolidated_csv(run))
    assert text.startswith("﻿")
    return list(csv.reader(io.StringIO(text.lstrip("﻿"))))


def _col(header, name):
    return header.index(name)


# --------------------------------------------------------------------------- #
# Header shape (case 21 / plan §9)
# --------------------------------------------------------------------------- #
def test_group_expands_in_field_position_with_exact_width():
    header = bulk_export.consolidated_header(FIELDS, {"Titel_Tracks": TRACKS_20})
    # 1 count + 20 items x 3 children x 3 cells + 1 overflow
    group_cols = [c for c in header if c.startswith("Titel_Tracks")]
    assert len(group_cols) == 1 + 20 * 3 * 3 + 1 == 182
    assert group_cols[0] == "Titel_Tracks_count"
    assert group_cols[-1] == "Titel_Tracks_overflow_json"
    # Expanded in place: after Gesamttitel, before Gesamtspieldauer
    assert header.index("Gesamttitel_ocr") < header.index("Titel_Tracks_count")
    assert header.index("Titel_Tracks_overflow_json") < header.index("Gesamtspieldauer_ocr")


def test_group_column_names_match_the_specification():
    header = bulk_export.consolidated_header(FIELDS, {"Titel_Tracks": TRACKS_20})
    for name in ["Titel_Tracks_count",
                 "Titel_Tracks_1_Lfd_Nr_ocr", "Titel_Tracks_1_Lfd_Nr_edited",
                 "Titel_Tracks_1_Lfd_Nr_confidence",
                 "Titel_Tracks_1_Titel_ocr", "Titel_Tracks_1_Titel_edited",
                 "Titel_Tracks_1_Titel_confidence",
                 "Titel_Tracks_1_Spieldauer_ocr", "Titel_Tracks_1_Spieldauer_edited",
                 "Titel_Tracks_1_Spieldauer_confidence",
                 "Titel_Tracks_20_Spieldauer_confidence",
                 "Titel_Tracks_overflow_json"]:
        assert name in header, name


def test_scalar_only_header_is_unchanged():
    """Case 1: a template without groups must produce the pre-feature header."""
    assert bulk_export.consolidated_header(["A", "B"]) == \
           bulk_export.consolidated_header(["A", "B"], None) == \
           ["bulk_run_id", "source_folder", "source_filename", "batch_id",
            "File", "Status", "Error", "Duration(s)", "Confidence_overall",
            "A_ocr", "A_edited", "A_confidence", "B_ocr", "B_edited", "B_confidence"]


# --------------------------------------------------------------------------- #
# One row per card, values in the right cells
# --------------------------------------------------------------------------- #
def test_one_row_per_card_with_all_tracks(   ):
    """Cases 24/25: Gesamttitel + tracks + individual durations + Gesamtspieldauer."""
    items = [
        {"Lfd_Nr": "1", "Titel": "The Man I Love", "Spieldauer": "3'21"},
        {"Lfd_Nr": "2", "Titel": "I Got Rhythm", "Spieldauer": "2'48"},
        {"Lfd_Nr": "3", "Titel": "Summertime", "Spieldauer": "4'06"},
    ]
    rows = _rows(_run([_card(items)]))
    header, row = rows[0], rows[1]
    assert len(rows) == 2, "exactly one data row per source card"

    assert row[_col(header, "Gesamttitel_ocr")] == "Gershwin - Evergreens"
    assert row[_col(header, "Gesamtspieldauer_ocr")] == "10'15"
    assert row[_col(header, "Titel_Tracks_count")] == "3"
    for i, item in enumerate(items, start=1):
        assert row[_col(header, f"Titel_Tracks_{i}_Lfd_Nr_ocr")] == item["Lfd_Nr"]
        assert row[_col(header, f"Titel_Tracks_{i}_Titel_ocr")] == item["Titel"]
        assert row[_col(header, f"Titel_Tracks_{i}_Spieldauer_ocr")] == item["Spieldauer"]
    # Unused positions stay empty, never shifted
    assert row[_col(header, "Titel_Tracks_4_Titel_ocr")] == ""
    assert row[_col(header, "Titel_Tracks_overflow_json")] == ""


def test_zero_items(   ):
    """Case 3."""
    rows = _rows(_run([_card([])]))
    header, row = rows[0], rows[1]
    assert row[_col(header, "Titel_Tracks_count")] == "0"
    assert row[_col(header, "Titel_Tracks_1_Titel_ocr")] == ""
    assert row[_col(header, "Titel_Tracks_overflow_json")] == ""


def test_missing_middle_duration_is_empty_and_does_not_shift(   ):
    """Case 7 at the export layer."""
    items = [
        {"Lfd_Nr": "1", "Titel": "Title 1", "Spieldauer": "3'21"},
        {"Lfd_Nr": "2", "Titel": "Title 2", "Spieldauer": ""},
        {"Lfd_Nr": "3", "Titel": "Title 3", "Spieldauer": "4'06"},
    ]
    rows = _rows(_run([_card(items)]))
    header, row = rows[0], rows[1]
    assert row[_col(header, "Titel_Tracks_2_Spieldauer_ocr")] == ""
    assert row[_col(header, "Titel_Tracks_3_Spieldauer_ocr")] == "4'06"
    assert row[_col(header, "Titel_Tracks_2_Titel_ocr")] == "Title 2"


def test_no_duration_is_ever_calculated(   ):
    """The exporter must not derive a missing value from the others."""
    items = [{"Titel": "A", "Spieldauer": ""}, {"Titel": "B", "Spieldauer": ""}]
    rows = _rows(_run([_card(items, dauer="10'00")]))
    header, row = rows[0], rows[1]
    assert row[_col(header, "Titel_Tracks_1_Spieldauer_ocr")] == ""
    assert row[_col(header, "Titel_Tracks_2_Spieldauer_ocr")] == ""


# --------------------------------------------------------------------------- #
# Edits and confidence (cases 10/11 at the export layer)
# --------------------------------------------------------------------------- #
def test_edited_and_confidence_columns(   ):
    items = [{"Lfd_Nr": "1", "Titel": "OCR-Titel", "Spieldauer": "3'21"}]
    edited = [{"Lfd_Nr": "1", "Titel": "Kurator-Titel", "Spieldauer": "3'21"}]
    conf = {"Titel_Tracks[0].Titel": 0.95, "Titel_Tracks[0].Spieldauer": 0.88,
            "Gesamttitel": 0.9}
    rows = _rows(_run([_card(items, edited=edited, confidence=conf)]))
    header, row = rows[0], rows[1]

    assert row[_col(header, "Titel_Tracks_1_Titel_ocr")] == "OCR-Titel"
    assert row[_col(header, "Titel_Tracks_1_Titel_edited")] == "Kurator-Titel"
    assert row[_col(header, "Titel_Tracks_1_Titel_confidence")] == "95"
    assert row[_col(header, "Titel_Tracks_1_Spieldauer_confidence")] == "88"
    assert row[_col(header, "Titel_Tracks_1_Lfd_Nr_confidence")] == ""
    assert row[_col(header, "Gesamttitel_confidence")] == "90"


def test_count_reflects_the_curators_view(   ):
    """After the curator removes an entry, count follows the edited array."""
    items = [{"Titel": "A"}, {"Titel": "B"}, {"Titel": "C"}]
    rows = _rows(_run([_card(items, edited=[{"Titel": "A"}])]))
    header, row = rows[0], rows[1]
    assert row[_col(header, "Titel_Tracks_count")] == "1"


# --------------------------------------------------------------------------- #
# Overflow (case 18) — never silently lost
# --------------------------------------------------------------------------- #
def test_overflow_is_lossless_and_count_is_truthful(   ):
    items = [{"Lfd_Nr": str(i), "Titel": f"T{i}", "Spieldauer": f"{i}'00"} for i in range(1, 6)]
    rows = _rows(_run([_card(items)], groups=TRACKS_2))   # width 2, five entries
    header, row = rows[0], rows[1]

    assert row[_col(header, "Titel_Tracks_count")] == "5", "the real total, not the width"
    assert row[_col(header, "Titel_Tracks_1_Titel_ocr")] == "T1"
    assert row[_col(header, "Titel_Tracks_2_Titel_ocr")] == "T2"
    overflow = json.loads(row[_col(header, "Titel_Tracks_overflow_json")])
    assert [o["Titel"] for o in overflow] == ["T3", "T4", "T5"]
    assert overflow[0]["Spieldauer"] == "3'00", "overflow keeps every child value"


def test_exactly_max_items_produces_no_overflow(   ):
    items = [{"Titel": "A"}, {"Titel": "B"}]
    rows = _rows(_run([_card(items)], groups=TRACKS_2))
    header, row = rows[0], rows[1]
    assert row[_col(header, "Titel_Tracks_count")] == "2"
    assert row[_col(header, "Titel_Tracks_overflow_json")] == ""


# --------------------------------------------------------------------------- #
# Robustness and format
# --------------------------------------------------------------------------- #
def test_corrupt_group_cell_degrades_to_zero_entries(   ):
    card = _card([])
    card["data"]["Titel_Tracks"] = "{kaputt"
    rows = _rows(_run([card]))
    header, row = rows[0], rows[1]
    assert row[_col(header, "Titel_Tracks_count")] == "0"
    assert len(row) == len(header)


def test_group_children_are_not_counted_as_unexpected_keys(caplog):
    """Children are schema, not drift — they must not trigger the drift log."""
    import logging
    items = [{"Lfd_Nr": "1", "Titel": "A", "Spieldauer": "1'00"}]
    with caplog.at_level(logging.INFO):
        _rows(_run([_card(items)]))
    assert "unexpected data key" not in caplog.text


def test_export_is_deterministic(   ):
    items = [{"Lfd_Nr": "1", "Titel": "A", "Spieldauer": "1'00"}]
    run = _run([_card(items)])
    assert "".join(bulk_export.iter_consolidated_csv(run)) == \
           "".join(bulk_export.iter_consolidated_csv(run))


def test_format_conventions_hold(   ):
    items = [{"Titel": 'Mit "Anführungszeichen"'}]
    text = "".join(bulk_export.iter_consolidated_csv(_run([_card(items)])))
    assert text.startswith("﻿")
    assert "\r\n" in text
    assert '"Mit ""Anführungszeichen"""' in text
    for line in text.lstrip("﻿").split("\r\n"):
        if line:
            assert line.startswith('"') and line.endswith('"')


def test_row_counts_still_matches(   ):
    items = [{"Titel": "A"}]
    run = _run([_card(items)])
    rows, failures = bulk_export.row_counts(run)
    assert rows == len(_rows(run)) - 1 == 1
    assert failures == 0


def test_failed_card_keeps_the_group_columns_empty(   ):
    run = _run([{"filename": "bad.jpg", "batch": "b", "success": False,
                 "error": "HTTP 500", "duration": 1.0}])
    rows = _rows(run)
    header, row = rows[0], rows[1]
    assert len(row) == len(header)
    assert row[_col(header, "Titel_Tracks_count")] == "0"
    assert row[_col(header, "Status")] == "failed"


def test_legacy_entries_card_keeps_column_width(   ):
    """Case 26: the Findmittel _entries path must still work and stay aligned."""
    card = {"filename": "page.jpg", "batch": "b", "success": True, "duration": 1.0,
            "data": {"_entries": json.dumps([{"Gesamttitel": "X"}, {"Gesamttitel": "Y"}])}}
    rows = _rows(_run([card]))
    header = rows[0]
    assert len(rows) == 3, "one row per entry, as before"
    for row in rows[1:]:
        assert len(row) == len(header)
    assert rows[1][_col(header, "Gesamttitel_ocr")] == "X"


# --------------------------------------------------------------------------- #
# Bulk integration (cases 20–23) — real orchestrator, mocked VLM
# --------------------------------------------------------------------------- #
AMIGA_FIELDS = ["Bestellnummer", "Gesamttitel", "Titel_Tracks", "Gesamtspieldauer", "Komponist"]
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16 + b"\xff\xd9"


@pytest.fixture
def bulk_env(tmp_path, monkeypatch):
    """Two source folders x one card, an AMIGA-shaped template with the group."""
    from app.core.config import settings
    from app.models.schemas import FieldGroup, GroupChild, TemplateCreate
    from app.services.bulk_manager import bulk_manager
    from app.services.template_service import template_service

    root = tmp_path / "amiga"
    for i in (1, 2):
        folder = root / f"Batch_{i:03d}"
        folder.mkdir(parents=True)
        (folder / f"card_{i}.JPG").write_bytes(JPEG)
    monkeypatch.setattr(settings, "BULK_IMPORT_ROOT", str(root))
    monkeypatch.setattr(bulk_manager, "runs_dir", tmp_path / "bulk_runs")

    tpl = template_service.create_template(TemplateCreate(
        name="AMIGA Tonband-Karteikarte (Test)", fields=AMIGA_FIELDS,
        field_groups={"Titel_Tracks": FieldGroup(
            max_items=20,
            fields=[GroupChild(name="Lfd_Nr"), GroupChild(name="Titel"),
                    GroupChild(name="Spieldauer")])},
    ))
    yield root, tpl
    template_service.delete_template(tpl.id)
    bulk_manager.release_run_lock()


def _amiga_payload(image_path, *a, **k):
    return ({
        "fields": {
            "Bestellnummer": "8 55 123",
            "Gesamttitel": "Gershwin - Evergreens",
            "Titel_Tracks": [
                {"Lfd_Nr": "1", "Titel": "The Man I Love", "Spieldauer": "3'21"},
                {"Lfd_Nr": "2", "Titel": "I Got Rhythm"},          # Dauer fehlt
                {"Lfd_Nr": "3", "Titel": "Summertime", "Spieldauer": "4'06"},
            ],
            "Gesamtspieldauer": "10'15",
            "Komponist": "Gershwin, George",
        },
        "confidence": {"Gesamttitel": 0.94, "Titel_Tracks[0].Titel": 0.95},
        "confidence_overall": 0.9,
    }, None)


def _run_bulk(tpl, monkeypatch):
    import asyncio
    from app.services import bulk_orchestrator
    from app.services.bulk_manager import bulk_manager
    from app.services.ocr_engine import ocr_engine

    monkeypatch.setattr(ocr_engine, "_call_vlm_api_resilient", _amiga_payload)
    run = bulk_manager.create_run(
        name="AMIGA Gruppen", template_id=tpl.id, schema_fields=AMIGA_FIELDS,
        provider="ollama", model="m",
        folders=[{"source_folder": f"Batch_{i:03d}", "images_total": 1} for i in (1, 2)],
        field_groups={"Titel_Tracks": {"max_items": 20,
                                       "fields": [{"name": "Lfd_Nr"}, {"name": "Titel"},
                                                  {"name": "Spieldauer"}]}},
    )
    rid = run["bulk_run_id"]

    async def go():
        await bulk_orchestrator.start_run(rid)
        await bulk_orchestrator._tasks[rid]
    asyncio.run(go())
    return bulk_manager.get_run(rid)


def test_bulk_freezes_field_groups(bulk_env, monkeypatch):
    """Case 20: max_items and children are frozen in run.json at creation."""
    _root, tpl = bulk_env
    from app.services.bulk_manager import bulk_manager
    run = bulk_manager.create_run(
        name="X", template_id=tpl.id, schema_fields=AMIGA_FIELDS, provider="ollama", model=None,
        folders=[{"source_folder": "Batch_001", "images_total": 1}],
        field_groups={"Titel_Tracks": {"max_items": 20, "fields": [{"name": "Titel"}]}},
    )
    on_disk = json.loads((bulk_manager.run_dir(run["bulk_run_id"]) / "run.json").read_text())
    assert on_disk["field_groups"]["Titel_Tracks"]["max_items"] == 20
    # run.json must still carry no extracted metadata — group defs are schema.
    raw = json.dumps(on_disk)
    assert "Gershwin" not in raw and "The Man I Love" not in raw


def test_bulk_consolidated_export_preserves_groups(bulk_env, monkeypatch):
    """Cases 22/24/25: full AMIGA card through the real orchestrator."""
    _root, tpl = bulk_env
    from app.services.batch_manager import batch_manager
    run = _run_bulk(tpl, monkeypatch)
    try:
        assert run["status"] == "completed"
        assert run["images_processed"] == 2

        rows = _rows(run)
        header = rows[0]
        assert len(rows) == 3, "one row per source card, both folders"

        for row in rows[1:]:
            assert row[_col(header, "Gesamttitel_ocr")] == "Gershwin - Evergreens"
            assert row[_col(header, "Gesamtspieldauer_ocr")] == "10'15"
            assert row[_col(header, "Titel_Tracks_count")] == "3"
            assert row[_col(header, "Titel_Tracks_1_Titel_ocr")] == "The Man I Love"
            assert row[_col(header, "Titel_Tracks_1_Spieldauer_ocr")] == "3'21"
            assert row[_col(header, "Titel_Tracks_2_Titel_ocr")] == "I Got Rhythm"
            assert row[_col(header, "Titel_Tracks_2_Spieldauer_ocr")] == "", \
                "missing middle duration stays empty end to end"
            assert row[_col(header, "Titel_Tracks_3_Spieldauer_ocr")] == "4'06"
            assert row[_col(header, "Titel_Tracks_1_Titel_confidence")] == "95"
            # Provenance intact
            assert row[_col(header, "source_folder")].startswith("Batch_00")
            assert row[_col(header, "source_filename")].endswith(".JPG")
            assert row[_col(header, "batch_id")]
    finally:
        for folder in run["folders"]:
            if folder.get("batch_name"):
                batch_manager.release_batch_lock(folder["batch_name"])
                batch_manager.delete_batch(folder["batch_name"])


def test_bulk_resume_does_not_reprocess_completed_cards(bulk_env, monkeypatch):
    """Cases 21/23: resume with groups sends nothing again."""
    _root, tpl = bulk_env
    from app.services import bulk_orchestrator
    from app.services.batch_manager import batch_manager
    from app.services.bulk_manager import bulk_manager
    from app.services.ocr_engine import ocr_engine

    run = _run_bulk(tpl, monkeypatch)
    rid = run["bulk_run_id"]
    try:
        sent = []

        def recording(image_path, *a, **k):
            sent.append(image_path.name)
            return _amiga_payload(image_path)

        monkeypatch.setattr(ocr_engine, "_call_vlm_api_resilient", recording)

        import asyncio

        async def go():
            await bulk_orchestrator.start_run(rid)
            await bulk_orchestrator._tasks[rid]
        asyncio.run(go())

        assert sent == [], "a completed run must not re-send any card"
        again = bulk_manager.get_run(rid)
        assert again["images_processed"] == 2
        # Group data survived the resume
        rows = _rows(again)
        assert rows[1][_col(rows[0], "Titel_Tracks_count")] == "3"
    finally:
        for folder in bulk_manager.get_run(rid)["folders"]:
            if folder.get("batch_name"):
                batch_manager.release_batch_lock(folder["batch_name"])
                batch_manager.delete_batch(folder["batch_name"])
