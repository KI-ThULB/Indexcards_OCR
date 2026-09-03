"""Regression tests for checkpoint format compatibility (bulk plan §3).

Two writers historically disagreed on the shape of ``checkpoint.json``: the OCR
engine wrote a bare list, the results API wrote ``{"results": [...], "audit":
[...]}`` and migrated a legacy list to that shape *on read*. Opening the Results
step therefore rewrote the file into a shape the engine's resume loop could not
iterate, breaking resume/retry for that batch.

These tests pin the fixed behaviour: both shapes are readable, reading never
writes, curator audit entries survive a resume, and an image that already
succeeded is never sent to the model again.

All VLM calls are mocked — no network, no Ollama/OpenRouter dependency.
"""
import asyncio
import json
from pathlib import Path

import pytest

from app.core.checkpoint import completed_filenames, read_checkpoint, write_checkpoint
from app.core.config import settings
from app.services.batch_manager import batch_manager
from app.services.ocr_engine import ocr_engine

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16 + b"\xff\xd9"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _make_batch(name: str, filenames=("a.jpg", "b.jpg")) -> Path:
    """Create a batch directory with config.json and the given image files."""
    batch_dir = Path(settings.BATCHES_DIR) / name
    batch_dir.mkdir(parents=True, exist_ok=True)
    (batch_dir / "config.json").write_text(json.dumps({"fields": ["Komponist"]}))
    for fn in filenames:
        (batch_dir / fn).write_bytes(JPEG)
    return batch_dir


def _result(filename: str, batch: str, success: bool = True) -> dict:
    """A checkpoint result row shaped like the engine writes it."""
    row: dict = {"filename": filename, "batch": batch, "success": success, "duration": 1.0}
    if success:
        row["data"] = {"Komponist": "Bach", "Datei": filename, "Batch": batch}
    else:
        row["error"] = "boom"
    return row


@pytest.fixture(autouse=True)
def _no_leaked_batches():
    """Delete batches this module creates so their completed_at stamps don't
    leak into other modules' global-state assertions."""
    before = set(batch_manager.list_batches())
    yield
    for name in set(batch_manager.list_batches()) - before:
        try:
            batch_manager.release_batch_lock(name)
            batch_manager.delete_batch(name)
        except Exception:
            pass


@pytest.fixture
def recorder(monkeypatch):
    """Mock the VLM call and record which image files were actually sent."""
    sent: list[str] = []

    def fake_call(image_path, *a, **k):
        sent.append(Path(image_path).name)
        return {"fields": {"Komponist": "Bach"}, "confidence_overall": 0.9}, None

    monkeypatch.setattr(ocr_engine, "_call_vlm_api_resilient", fake_call)
    return sent


def _run(batch_dir: Path):
    return asyncio.run(
        ocr_engine.process_batch(batch_dir=batch_dir, fields=["Komponist"], api_key="k")
    )


# --------------------------------------------------------------------------- #
# read_checkpoint / write_checkpoint unit behaviour
# --------------------------------------------------------------------------- #
def test_read_legacy_flat_list(tmp_path):
    """Case 1 (unit): a legacy bare array normalises to (results, [])."""
    cp = tmp_path / "checkpoint.json"
    cp.write_text(json.dumps([_result("a.jpg", "B")]))
    results, audit = read_checkpoint(cp)
    assert [r["filename"] for r in results] == ["a.jpg"]
    assert audit == []


def test_read_object_shape(tmp_path):
    """Case 2 (unit): the current object shape round-trips results + audit."""
    cp = tmp_path / "checkpoint.json"
    cp.write_text(json.dumps({"results": [_result("a.jpg", "B")], "audit": [{"id": "1"}]}))
    results, audit = read_checkpoint(cp)
    assert [r["filename"] for r in results] == ["a.jpg"]
    assert audit == [{"id": "1"}]


def test_read_is_pure_no_write_on_read(tmp_path):
    """Reading a legacy file must NOT rewrite it (that side effect caused the bug)."""
    cp = tmp_path / "checkpoint.json"
    raw = json.dumps([_result("a.jpg", "B")])
    cp.write_text(raw)
    before = cp.stat().st_mtime_ns
    read_checkpoint(cp)
    read_checkpoint(cp)
    assert cp.read_text() == raw
    assert cp.stat().st_mtime_ns == before


def test_write_is_atomic_and_object_shaped(tmp_path):
    """write_checkpoint always emits the object shape and leaves no temp files."""
    cp = tmp_path / "checkpoint.json"
    write_checkpoint(cp, [_result("a.jpg", "B")], [{"id": "1"}])
    data = json.loads(cp.read_text())
    assert set(data) == {"results", "audit"}
    assert data["audit"] == [{"id": "1"}]
    # No leftover temp artefacts in the directory
    assert {p.name for p in tmp_path.iterdir()} == {"checkpoint.json"}


def test_write_upgrades_legacy_file_in_place(tmp_path):
    """A legacy file is upgraded on the next real write (not on read)."""
    cp = tmp_path / "checkpoint.json"
    cp.write_text(json.dumps([_result("a.jpg", "B")]))
    results, audit = read_checkpoint(cp)
    write_checkpoint(cp, results, audit)
    assert isinstance(json.loads(cp.read_text()), dict)


def test_read_raises_on_corrupt_json(tmp_path):
    """Corrupt JSON raises so each caller decides how to react."""
    cp = tmp_path / "checkpoint.json"
    cp.write_text("{not json")
    with pytest.raises(Exception):
        read_checkpoint(cp)


def test_completed_filenames_only_successes():
    rows = [_result("a.jpg", "B"), _result("b.jpg", "B", success=False)]
    assert completed_filenames(rows) == {"a.jpg"}


# --------------------------------------------------------------------------- #
# Case 1 + 6: resume from a LEGACY flat-list checkpoint
# --------------------------------------------------------------------------- #
def test_resume_from_legacy_flat_list_checkpoint(recorder):
    batch = "cp_legacy"
    batch_dir = _make_batch(batch)
    # Legacy bare-array checkpoint: a.jpg already done.
    (batch_dir / "checkpoint.json").write_text(json.dumps([_result("a.jpg", batch)]))

    results = _run(batch_dir)

    assert recorder == ["b.jpg"], "already-successful image must not be re-sent"
    assert {r["filename"] for r in results} == {"a.jpg", "b.jpg"}
    # Checkpoint is now the canonical object shape
    assert isinstance(json.loads((batch_dir / "checkpoint.json").read_text()), dict)


# --------------------------------------------------------------------------- #
# Case 2: resume from the CURRENT {results, audit} checkpoint
# --------------------------------------------------------------------------- #
def test_resume_from_object_checkpoint(recorder):
    batch = "cp_object"
    batch_dir = _make_batch(batch)
    write_checkpoint(batch_dir / "checkpoint.json", [_result("a.jpg", batch)], [])

    results = _run(batch_dir)

    assert recorder == ["b.jpg"]
    assert {r["filename"] for r in results} == {"a.jpg", "b.jpg"}


# --------------------------------------------------------------------------- #
# Case 3: viewing Results before resume — the exact bug path
# --------------------------------------------------------------------------- #
def test_resume_after_viewing_results(client, recorder):
    """GET /results then resume. Before the fix this left results == ["results"],
    crashed on r["filename"] and marked the batch failed."""
    batch = "cp_view_then_resume"
    batch_dir = _make_batch(batch)
    (batch_dir / "checkpoint.json").write_text(json.dumps([_result("a.jpg", batch)]))

    # Open the Results step
    resp = client.get(f"/api/v1/batches/{batch}/results")
    assert resp.status_code == 200
    assert [r["filename"] for r in resp.json()["results"]] == ["a.jpg"]

    results = _run(batch_dir)

    assert recorder == ["b.jpg"]
    assert {r["filename"] for r in results} == {"a.jpg", "b.jpg"}
    assert all(isinstance(r, dict) for r in results)


# --------------------------------------------------------------------------- #
# Case 4: retry after viewing results
# --------------------------------------------------------------------------- #
def test_retry_image_after_viewing_results(client, recorder):
    """A failed card moved to _errors/ can still be retried after the Results
    step has been opened."""
    batch = "cp_view_then_retry"
    batch_dir = _make_batch(batch, filenames=("a.jpg",))
    error_dir = batch_dir / "_errors"
    error_dir.mkdir()
    (error_dir / "b.jpg").write_bytes(JPEG)
    (batch_dir / "checkpoint.json").write_text(
        json.dumps([_result("a.jpg", batch), _result("b.jpg", batch, success=False)])
    )

    assert client.get(f"/api/v1/batches/{batch}/results").status_code == 200

    resp = client.post(f"/api/v1/batches/{batch}/retry-image/b.jpg")
    assert resp.status_code == 200, resp.text

    # TestClient runs the queued background task before returning, so the retry
    # has already completed here: b.jpg was moved back out of _errors/, its stale
    # checkpoint row dropped, and only that one image re-sent to the model.
    assert recorder == ["b.jpg"], "retry must not re-send the already-successful card"
    assert (batch_dir / "b.jpg").exists()

    results, _ = read_checkpoint(batch_dir / "checkpoint.json")
    assert {r["filename"] for r in results} == {"a.jpg", "b.jpg"}
    assert all(r["success"] for r in results)
    # Before the fix this path raised TypeError and marked the batch failed.
    history = {e["batch_name"]: e["status"] for e in batch_manager._read_history_raw()}
    assert history.get(batch) != "failed"


# --------------------------------------------------------------------------- #
# Case 5: audit entries survive resume and retry
# --------------------------------------------------------------------------- #
def test_audit_entries_survive_resume(recorder):
    """Curator audit entries must be carried through a resume, not discarded.
    The engine used to write a bare list, silently dropping them."""
    batch = "cp_audit"
    batch_dir = _make_batch(batch)
    audit = [{"id": "1", "op": "bulk-transform", "column": "Komponist", "affected": 3}]
    write_checkpoint(batch_dir / "checkpoint.json", [_result("a.jpg", batch)], audit)

    _run(batch_dir)

    results, audit_after = read_checkpoint(batch_dir / "checkpoint.json")
    assert audit_after == audit, "audit must survive resume untouched"
    assert {r["filename"] for r in results} == {"a.jpg", "b.jpg"}


def test_audit_entries_survive_patch_then_resume(client, recorder):
    """A curator edit (PATCH) writes audit; a later resume must preserve it."""
    batch = "cp_audit_patch"
    batch_dir = _make_batch(batch)
    write_checkpoint(batch_dir / "checkpoint.json", [_result("a.jpg", batch)], [])

    resp = client.patch(
        f"/api/v1/batches/{batch}/results/a.jpg",
        json={
            "field": "Komponist",
            "value": "Bach, J. S.",
            "audit_entry": {"id": "9", "op": "cluster-merge", "column": "Komponist"},
        },
    )
    assert resp.status_code == 200, resp.text

    _run(batch_dir)

    results, audit_after = read_checkpoint(batch_dir / "checkpoint.json")
    assert [a["id"] for a in audit_after] == ["9"]
    row = next(r for r in results if r["filename"] == "a.jpg")
    assert row["edited_data"]["Komponist"] == "Bach, J. S."


# --------------------------------------------------------------------------- #
# Case 6: no duplicate processing
# --------------------------------------------------------------------------- #
def test_fully_processed_batch_sends_nothing(recorder):
    batch = "cp_complete"
    batch_dir = _make_batch(batch)
    write_checkpoint(
        batch_dir / "checkpoint.json",
        [_result("a.jpg", batch), _result("b.jpg", batch)],
        [],
    )

    results = _run(batch_dir)

    assert recorder == [], "a fully processed batch must not call the model again"
    assert len(results) == 2


def test_failed_image_is_retried_on_resume(recorder):
    """success=False rows are not 'completed' — they are re-processed."""
    batch = "cp_failed_row"
    batch_dir = _make_batch(batch)
    write_checkpoint(
        batch_dir / "checkpoint.json",
        [_result("a.jpg", batch), _result("b.jpg", batch, success=False)],
        [],
    )

    _run(batch_dir)

    assert recorder == ["b.jpg"]
