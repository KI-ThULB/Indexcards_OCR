"""Bulk-run state model: atomic persistence, single-run lock, restart recovery."""
import json

from app.core.config import settings
from app.services.bulk_manager import (
    FOLDER_COMPLETED,
    FOLDER_PENDING,
    FOLDER_RUNNING,
    STATUS_INTERRUPTED,
    STATUS_PAUSED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    BulkManager,
)


def _mgr(tmp_path) -> BulkManager:
    return BulkManager(runs_dir=str(tmp_path / "bulk_runs"))


def _create(mgr, folders=("A", "B"), **kw):
    return mgr.create_run(
        name="AMIGA Tonbandkartei",
        template_id="tpl-1",
        schema_fields=["Komponist", "Signatur"],
        provider="ollama",
        model="qwen3-vl:235b",
        folders=[{"source_folder": f, "images_total": 2} for f in folders],
        **kw,
    )


# --------------------------------------------------------------------------- #
# Defaults
# --------------------------------------------------------------------------- #
def test_bulk_disabled_by_default():
    """Bulk mode must be entirely unavailable until an import root is configured."""
    assert settings.BULK_IMPORT_ROOT == ""
    assert settings.bulk_enabled is False


def test_bulk_enabled_requires_existing_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "BULK_IMPORT_ROOT", str(tmp_path / "nope"))
    assert settings.bulk_enabled is False
    monkeypatch.setattr(settings, "BULK_IMPORT_ROOT", str(tmp_path))
    assert settings.bulk_enabled is True


def test_bulk_defaults():
    assert settings.BULK_IMPORT_MODE == "hardlink"
    assert settings.BULK_CONTINUE_ON_BATCH_ERROR is True
    assert settings.BULK_MAX_FOLDERS == 200
    assert settings.RATE_LIMIT_BULK_START == "6/minute"


# --------------------------------------------------------------------------- #
# Create / read / update
# --------------------------------------------------------------------------- #
def test_create_run_persists_frozen_schema(tmp_path):
    mgr = _mgr(tmp_path)
    run = _create(mgr)

    on_disk = json.loads((mgr.run_dir(run["bulk_run_id"]) / "run.json").read_text())
    assert on_disk["status"] == STATUS_QUEUED
    assert on_disk["schema_fields"] == ["Komponist", "Signatur"]
    assert on_disk["folders_total"] == 2
    assert on_disk["images_total"] == 4
    assert [f["status"] for f in on_disk["folders"]] == [FOLDER_PENDING, FOLDER_PENDING]


def test_run_state_carries_no_extracted_metadata(tmp_path):
    """run.json is orchestration state only — no OCR text, no personal data."""
    mgr = _mgr(tmp_path)
    run = _create(mgr)
    raw = (mgr.run_dir(run["bulk_run_id"]) / "run.json").read_text()
    for forbidden in ("data", "edited_data", "confidence", "_entries"):
        assert f'"{forbidden}"' not in raw


def test_folder_order_is_the_configured_order(tmp_path):
    mgr = _mgr(tmp_path)
    run = _create(mgr, folders=("Z_last", "A_first", "M_mid"))
    assert [f["source_folder"] for f in run["folders"]] == ["Z_last", "A_first", "M_mid"]


def test_update_run_and_folder(tmp_path):
    mgr = _mgr(tmp_path)
    rid = _create(mgr)["bulk_run_id"]

    mgr.update_run(rid, status=STATUS_RUNNING, current_folder="A")
    mgr.update_folder(rid, "A", status=FOLDER_COMPLETED, images_processed=2)

    run = mgr.get_run(rid)
    assert run["status"] == STATUS_RUNNING
    assert run["current_folder"] == "A"
    assert run["folders"][0]["status"] == FOLDER_COMPLETED


def test_recount_progress_is_derived_not_incremented(tmp_path):
    """Counters are recomputed from folder entries, so a resume cannot double-count."""
    mgr = _mgr(tmp_path)
    rid = _create(mgr)["bulk_run_id"]
    mgr.update_folder(rid, "A", status=FOLDER_COMPLETED, images_processed=2, images_failed=1)
    run = mgr.recount_progress(mgr.get_run(rid))

    assert run["folders_completed"] == 1
    assert run["images_processed"] == 2
    assert run["images_failed"] == 1

    # Recounting twice must not change anything.
    again = mgr.recount_progress(run)
    assert again["images_processed"] == 2


def test_get_run_rejects_non_uuid_id(tmp_path):
    """A run id is a uuid4, so it can never be a traversal payload."""
    mgr = _mgr(tmp_path)
    assert mgr.get_run("../../etc") is None
    assert mgr.get_run("not-a-uuid") is None


def test_list_runs_newest_first(tmp_path):
    mgr = _mgr(tmp_path)
    first = _create(mgr)["bulk_run_id"]
    second = _create(mgr)["bulk_run_id"]
    mgr.update_run(first, created_at="2020-01-01T00:00:00+00:00")
    mgr.update_run(second, created_at="2030-01-01T00:00:00+00:00")
    assert [r["bulk_run_id"] for r in mgr.list_runs()] == [second, first]


# --------------------------------------------------------------------------- #
# Atomic writes
# --------------------------------------------------------------------------- #
def test_writes_leave_no_temp_files(tmp_path):
    mgr = _mgr(tmp_path)
    rid = _create(mgr)["bulk_run_id"]
    for i in range(5):
        mgr.update_run(rid, images_processed=i)
    assert {p.name for p in mgr.run_dir(rid).iterdir()} == {"run.json"}


def test_run_json_stays_valid_across_many_updates(tmp_path):
    mgr = _mgr(tmp_path)
    rid = _create(mgr)["bulk_run_id"]
    for i in range(20):
        mgr.update_run(rid, images_processed=i)
        json.loads((mgr.run_dir(rid) / "run.json").read_text())


# --------------------------------------------------------------------------- #
# Single-run lock
# --------------------------------------------------------------------------- #
def test_single_run_lock_is_exclusive(tmp_path):
    mgr = _mgr(tmp_path)
    a = _create(mgr)["bulk_run_id"]
    b = _create(mgr)["bulk_run_id"]

    assert mgr.acquire_run_lock(a) is True
    assert mgr.acquire_run_lock(b) is False, "two bulk runs must not execute concurrently"
    assert mgr.locked_run_id() == a
    assert mgr.is_any_run_active() is True

    mgr.release_run_lock()
    assert mgr.is_any_run_active() is False
    assert mgr.acquire_run_lock(b) is True


def test_release_run_lock_is_idempotent(tmp_path):
    mgr = _mgr(tmp_path)
    mgr.release_run_lock()
    mgr.release_run_lock()
    assert mgr.is_any_run_active() is False


# --------------------------------------------------------------------------- #
# Restart recovery (D2 — never auto-resume)
# --------------------------------------------------------------------------- #
def test_running_run_becomes_interrupted_at_startup(tmp_path):
    mgr = _mgr(tmp_path)
    rid = _create(mgr)["bulk_run_id"]
    mgr.update_run(rid, status=STATUS_RUNNING, current_folder="A", current_batch_id="A_ab12cd34",
                   last_image="IMG_0007.JPG")
    mgr.update_folder(rid, "A", status=FOLDER_RUNNING)

    assert mgr.mark_interrupted_runs() == [rid]

    run = mgr.get_run(rid)
    assert run["status"] == STATUS_INTERRUPTED
    assert run["interrupted_at"]
    # The operator must be able to see exactly where it stopped.
    assert run["current_folder"] == "A"
    assert run["current_batch_id"] == "A_ab12cd34"
    assert run["last_image"] == "IMG_0007.JPG"
    # The mid-flight folder is no longer "running"
    assert run["folders"][0]["status"] == FOLDER_PENDING


def test_startup_does_not_touch_paused_or_finished_runs(tmp_path):
    mgr = _mgr(tmp_path)
    paused = _create(mgr)["bulk_run_id"]
    done = _create(mgr)["bulk_run_id"]
    mgr.update_run(paused, status=STATUS_PAUSED)
    mgr.update_run(done, status="completed")

    assert mgr.mark_interrupted_runs() == []
    assert mgr.get_run(paused)["status"] == STATUS_PAUSED
    assert mgr.get_run(done)["status"] == "completed"


def test_startup_clears_stale_lock(tmp_path):
    """A lock from a dead process must not block every future run."""
    mgr = _mgr(tmp_path)
    rid = _create(mgr)["bulk_run_id"]
    mgr.acquire_run_lock(rid)
    mgr.update_run(rid, status=STATUS_RUNNING)

    mgr.mark_interrupted_runs()

    assert mgr.is_any_run_active() is False


def test_startup_clears_stale_pause_and_cancel_requests(tmp_path):
    mgr = _mgr(tmp_path)
    rid = _create(mgr)["bulk_run_id"]
    mgr.update_run(rid, status=STATUS_RUNNING, pause_requested=True, cancel_requested=True)
    mgr.mark_interrupted_runs()
    run = mgr.get_run(rid)
    assert run["pause_requested"] is False
    assert run["cancel_requested"] is False
