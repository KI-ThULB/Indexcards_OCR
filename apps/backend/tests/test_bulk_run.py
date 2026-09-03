"""Sequential bulk orchestration: order, resume, pause/cancel, error handling.

All VLM calls are mocked; nothing here touches Ollama, OpenRouter or the network.
"""
import asyncio
import json

import pytest

from app.core.checkpoint import read_checkpoint, write_checkpoint
from app.core.config import settings
from app.models.schemas import TemplateCreate
from app.services import bulk_import, bulk_orchestrator
from app.services.batch_manager import batch_manager
from app.services.bulk_manager import (
    FOLDER_COMPLETED,
    FOLDER_COMPLETED_WITH_ERRORS,
    FOLDER_FAILED,
    FOLDER_PENDING,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_COMPLETED_WITH_ERRORS,
    STATUS_FAILED,
    STATUS_INTERRUPTED,
    STATUS_PAUSED,
    STATUS_RUNNING,
    bulk_manager,
)
from app.services.ocr_engine import ocr_engine
from app.services.template_service import template_service

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16 + b"\xff\xd9"
FIELDS = ["Komponist", "Signatur"]


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _clean_state():
    """Delete batches and release locks this module creates."""
    before = set(batch_manager.list_batches())
    yield
    bulk_manager.release_run_lock()
    for name in set(batch_manager.list_batches()) - before:
        try:
            batch_manager.release_batch_lock(name)
            batch_manager.delete_batch(name)
        except Exception:
            pass


@pytest.fixture
def import_root(tmp_path, monkeypatch):
    """Three folders, two mixed-case JPGs each — the documented smoke shape."""
    root = tmp_path / "amiga"
    for i in range(1, 4):
        folder = root / f"Batch_{i:03d}"
        folder.mkdir(parents=True)
        (folder / f"IMG_{i}_a.JPG").write_bytes(JPEG)
        (folder / f"IMG_{i}_b.jpeg").write_bytes(JPEG)
    monkeypatch.setattr(settings, "BULK_IMPORT_ROOT", str(root))
    return root


@pytest.fixture
def runs_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(bulk_manager, "runs_dir", tmp_path / "bulk_runs")
    return bulk_manager.runs_dir


@pytest.fixture
def template():
    # Use the real TemplateCreate model rather than a duck-typed double, so the
    # fixture cannot drift out of sync when the template schema gains a field.
    tpl = template_service.create_template(
        TemplateCreate(name="AMIGA Tonbandkartei", fields=FIELDS)
    )
    yield tpl
    template_service.delete_template(tpl.id)


@pytest.fixture
def calls(monkeypatch):
    """Mocked VLM; records (batch_name, filename) for every card actually sent."""
    seen: list = []

    def fake(image_path, *a, **k):
        seen.append(image_path.name)
        return {"fields": {"Komponist": "Bach", "Signatur": "Spez. 1"}, "confidence_overall": 0.9}, None

    monkeypatch.setattr(ocr_engine, "_call_vlm_api_resilient", fake)
    return seen


def _create_run(template, folders=("Batch_001", "Batch_002", "Batch_003")):
    listing = {f["name"]: f["images_total"] for f in bulk_import.list_source_folders()["folders"]}
    return bulk_manager.create_run(
        name="AMIGA Tonbandkartei",
        template_id=template.id,
        schema_fields=FIELDS,
        provider="ollama",
        model="qwen3-vl:235b",
        folders=[{"source_folder": f, "images_total": listing.get(f, 0)} for f in folders],
    )


def _run_to_completion(run_id):
    async def go():
        await bulk_orchestrator.start_run(run_id)
        await bulk_orchestrator._tasks[run_id]

    asyncio.run(go())
    return bulk_manager.get_run(run_id)


# --------------------------------------------------------------------------- #
# Happy path — sequential, same template everywhere
# --------------------------------------------------------------------------- #
def test_processes_all_folders_sequentially(import_root, runs_dir, template, calls):
    run = _run_to_completion(_create_run(template)["bulk_run_id"])

    assert run["status"] == STATUS_COMPLETED
    assert run["folders_completed"] == 3
    assert run["images_processed"] == 6
    assert run["images_failed"] == 0
    assert [f["status"] for f in run["folders"]] == [FOLDER_COMPLETED] * 3
    assert run["completed_at"]
    # Every image was sent exactly once.
    assert sorted(calls) == sorted([
        f"IMG_{i}_{s}.{e}" for i in (1, 2, 3) for s, e in (("a", "JPG"), ("b", "jpeg"))
    ])


def test_folders_are_processed_in_configured_order(import_root, runs_dir, template, calls):
    order = ("Batch_003", "Batch_001", "Batch_002")
    run = _run_to_completion(_create_run(template, folders=order)["bulk_run_id"])

    assert [f["source_folder"] for f in run["folders"]] == list(order)
    # Sequential: folder 3's images precede folder 1's, which precede folder 2's.
    assert [c.split("_")[1] for c in calls] == ["3", "3", "1", "1", "2", "2"]


def test_uppercase_extensions_are_processed(import_root, runs_dir, template, calls):
    _run_to_completion(_create_run(template, folders=("Batch_001",))["bulk_run_id"])
    assert "IMG_1_a.JPG" in calls


def test_same_template_applied_to_every_batch(import_root, runs_dir, template, calls):
    run = _run_to_completion(_create_run(template)["bulk_run_id"])
    for folder in run["folders"]:
        config = json.loads(
            (batch_manager.get_batch_path(folder["batch_name"]) / "config.json").read_text()
        )
        assert config["fields"] == FIELDS


def test_each_folder_becomes_an_ordinary_batch(import_root, runs_dir, template, calls):
    """Bulk batches must be normal batches — visible in history, purgeable, served."""
    run = _run_to_completion(_create_run(template)["bulk_run_id"])
    history = {e["batch_name"] for e in batch_manager._read_history_raw()}
    for folder in run["folders"]:
        assert folder["batch_name"] in history
        assert (batch_manager.get_batch_path(folder["batch_name"]) / "checkpoint.json").exists()


def test_no_cross_folder_parallelism(import_root, runs_dir, template, monkeypatch):
    """Only one batch may be in flight at any moment."""
    in_flight = {"now": 0, "max": 0}

    def fake(image_path, *a, **k):
        return {"fields": {"Komponist": "Bach"}}, None

    monkeypatch.setattr(ocr_engine, "_call_vlm_api_resilient", fake)

    real_process = ocr_engine.process_batch

    async def tracked(*a, **k):
        in_flight["now"] += 1
        in_flight["max"] = max(in_flight["max"], in_flight["now"])
        try:
            return await real_process(*a, **k)
        finally:
            in_flight["now"] -= 1

    monkeypatch.setattr(ocr_engine, "process_batch", tracked)
    _run_to_completion(_create_run(template)["bulk_run_id"])

    assert in_flight["max"] == 1


# --------------------------------------------------------------------------- #
# Resume — completed folders and completed images are never redone
# --------------------------------------------------------------------------- #
def test_resume_skips_completed_folders_and_images(import_root, runs_dir, template, calls):
    run_id = _create_run(template)["bulk_run_id"]
    _run_to_completion(run_id)
    assert len(calls) == 6

    calls.clear()
    # A second start is a no-op resume: everything is already done.
    run = _run_to_completion(run_id)
    assert calls == [], "a completed run must not re-send anything to the model"
    assert run["status"] == STATUS_COMPLETED
    assert run["images_processed"] == 6


def test_resume_after_interruption_continues_from_checkpoints(
    import_root, runs_dir, template, calls
):
    """Simulates the documented restart walkthrough: folder 1 done, folder 2
    half done, then a restart marks the run interrupted and Resume finishes it."""
    run_id = _create_run(template)["bulk_run_id"]

    # Folder 1 fully processed, folder 2 half processed.
    b1 = bulk_import.materialise_folder("Batch_001", fields=FIELDS)["batch_name"]
    b2 = bulk_import.materialise_folder("Batch_002", fields=FIELDS)["batch_name"]
    write_checkpoint(
        batch_manager.get_batch_path(b1) / "checkpoint.json",
        [
            {"filename": "IMG_1_a.JPG", "batch": b1, "success": True, "duration": 1.0, "data": {}},
            {"filename": "IMG_1_b.jpeg", "batch": b1, "success": True, "duration": 1.0, "data": {}},
        ],
        [],
    )
    write_checkpoint(
        batch_manager.get_batch_path(b2) / "checkpoint.json",
        [{"filename": "IMG_2_a.JPG", "batch": b2, "success": True, "duration": 1.0, "data": {}}],
        [],
    )
    bulk_manager.update_folder(run_id, "Batch_001", batch_name=b1, status=FOLDER_COMPLETED,
                               images_processed=2)
    bulk_manager.update_folder(run_id, "Batch_002", batch_name=b2)
    bulk_manager.update_run(run_id, status=STATUS_RUNNING, current_folder="Batch_002",
                            current_batch_id=b2, last_image="IMG_2_a.JPG")

    # ── restart ──
    assert bulk_manager.mark_interrupted_runs() == [run_id]
    interrupted = bulk_manager.get_run(run_id)
    assert interrupted["status"] == STATUS_INTERRUPTED
    assert interrupted["interrupted_at"]
    assert interrupted["current_folder"] == "Batch_002"
    assert interrupted["last_image"] == "IMG_2_a.JPG"

    # ── explicit Resume ──
    run = _run_to_completion(run_id)

    assert run["status"] == STATUS_COMPLETED
    assert sorted(calls) == ["IMG_2_b.jpeg", "IMG_3_a.JPG", "IMG_3_b.jpeg"], (
        "resume must only process the unfinished image and the remaining folder"
    )
    assert run["images_processed"] == 6
    assert run["folders_completed"] == 3


def test_restart_never_auto_resumes(import_root, runs_dir, template, calls):
    """The startup hook marks a run interrupted and starts nothing (D2)."""
    run_id = _create_run(template)["bulk_run_id"]
    bulk_manager.update_run(run_id, status=STATUS_RUNNING)

    bulk_manager.mark_interrupted_runs()

    assert bulk_manager.get_run(run_id)["status"] == STATUS_INTERRUPTED
    assert calls == [], "no images may be sent to the model without an explicit Resume"
    assert bulk_orchestrator.is_task_active(run_id) is False


# --------------------------------------------------------------------------- #
# Recoverable image-level failures
# --------------------------------------------------------------------------- #
def test_one_failed_image_does_not_corrupt_the_run(import_root, runs_dir, template, monkeypatch):
    def fake(image_path, *a, **k):
        if image_path.name == "IMG_2_b.jpeg":
            return None, "HTTP 500: upstream exploded"
        return {"fields": {"Komponist": "Bach"}}, None

    monkeypatch.setattr(ocr_engine, "_call_vlm_api_resilient", fake)
    run = _run_to_completion(_create_run(template)["bulk_run_id"])

    assert run["status"] == STATUS_COMPLETED_WITH_ERRORS
    assert run["images_failed"] == 1
    assert run["images_processed"] == 6
    statuses = [f["status"] for f in run["folders"]]
    assert statuses == [FOLDER_COMPLETED, FOLDER_COMPLETED_WITH_ERRORS, FOLDER_COMPLETED]
    # The other folders' results are intact.
    good = run["folders"][2]["batch_name"]
    results, _ = read_checkpoint(batch_manager.get_batch_path(good) / "checkpoint.json")
    assert all(r["success"] for r in results)


def test_failed_card_moves_to_errors_dir(import_root, runs_dir, template, monkeypatch):
    def fake(image_path, *a, **k):
        if image_path.name == "IMG_1_b.jpeg":
            return None, "HTTP 500"
        return {"fields": {"Komponist": "Bach"}}, None

    monkeypatch.setattr(ocr_engine, "_call_vlm_api_resilient", fake)
    run = _run_to_completion(_create_run(template, folders=("Batch_001",))["bulk_run_id"])

    errors = batch_manager.get_batch_path(run["folders"][0]["batch_name"]) / "_errors"
    assert {p.name for p in errors.iterdir()} == {"IMG_1_b.jpeg"}


# --------------------------------------------------------------------------- #
# Structural failures stop the run
# --------------------------------------------------------------------------- #
def test_folder_with_zero_successes_fails_the_run(import_root, runs_dir, template, monkeypatch):
    """A folder that yields nothing is a configuration fault, not a bad card."""
    monkeypatch.setattr(
        ocr_engine, "_call_vlm_api_resilient", lambda *a, **k: (None, "HTTP 500")
    )
    run = _run_to_completion(_create_run(template)["bulk_run_id"])

    assert run["status"] == STATUS_FAILED
    assert run["error"]
    assert run["folders"][0]["status"] == FOLDER_FAILED
    # Following folders were never started.
    assert run["folders"][1]["status"] == FOLDER_PENDING
    assert run["folders"][1]["batch_name"] is None


def test_credential_failure_stops_the_run(import_root, runs_dir, template, monkeypatch):
    monkeypatch.setattr(
        ocr_engine, "_call_vlm_api_resilient", lambda *a, **k: (None, "Ungültiger API Key (401)")
    )
    run = _run_to_completion(_create_run(template)["bulk_run_id"])

    assert run["status"] == STATUS_FAILED
    assert "credential" in run["error"].lower()
    assert "Batch_001" in run["error"], "the error must name the folder it stopped on"


def test_run_state_never_stores_the_raw_provider_message(
    import_root, runs_dir, template, monkeypatch
):
    """A provider message can echo part of the model's response, and run.json is
    documented as carrying no extracted metadata. The detail belongs in the log."""
    leak = "HTTP 401 unauthorized — echo: Bach, Johann Sebastian, Spez. 12.345"
    monkeypatch.setattr(ocr_engine, "_call_vlm_api_resilient", lambda *a, **k: (None, leak))

    run_id = _create_run(template)["bulk_run_id"]
    run = _run_to_completion(run_id)

    assert run["status"] == STATUS_FAILED
    raw = (bulk_manager.run_dir(run_id) / "run.json").read_text()
    assert "Bach, Johann Sebastian" not in raw
    assert "Spez. 12.345" not in raw


def test_stored_error_is_bounded(import_root, runs_dir, template, monkeypatch):
    """run.json is rewritten after every image, so an error string must stay small."""
    assert len(bulk_orchestrator._safe_detail("x" * 5000)) <= 200
    assert bulk_orchestrator._safe_detail("a\n  b\tc") == "a b c"


def test_missing_template_stops_the_run_before_any_folder(
    import_root, runs_dir, template, calls
):
    run_id = _create_run(template)["bulk_run_id"]
    template_service.delete_template(template.id)

    run = _run_to_completion(run_id)

    assert run["status"] == STATUS_FAILED
    assert calls == [], "nothing may be sent when the configuration is invalid"


def test_unreachable_import_root_stops_the_run(import_root, runs_dir, template, monkeypatch):
    run_id = _create_run(template)["bulk_run_id"]
    monkeypatch.setattr(settings, "BULK_IMPORT_ROOT", "")

    run = _run_to_completion(run_id)
    assert run["status"] == STATUS_FAILED


def test_vanished_source_folder_stops_the_run(import_root, runs_dir, template, calls):
    import shutil

    run_id = _create_run(template)["bulk_run_id"]
    shutil.rmtree(import_root / "Batch_002")

    run = _run_to_completion(run_id)

    assert run["status"] == STATUS_FAILED
    assert run["folders"][0]["status"] == FOLDER_COMPLETED  # folder 1 kept its results
    assert run["folders"][1]["status"] == FOLDER_FAILED


def test_continue_on_batch_error_false_stops_after_a_failed_folder(
    import_root, runs_dir, template, monkeypatch
):
    monkeypatch.setattr(settings, "BULK_CONTINUE_ON_BATCH_ERROR", False)

    run_id = _create_run(template)["bulk_run_id"]
    # Make folder 2's batch lock unavailable so that folder fails recoverably.
    run = bulk_manager.get_run(run_id)

    def fake(image_path, *a, **k):
        return {"fields": {"Komponist": "Bach"}}, None

    monkeypatch.setattr(ocr_engine, "_call_vlm_api_resilient", fake)

    original = bulk_import.materialise_folder
    calls = {"n": 0}

    def flaky(folder, **kw):
        result = original(folder, **kw)
        calls["n"] += 1
        if folder == "Batch_002":
            # Simulate a stale lock on the freshly created batch.
            batch_manager.acquire_batch_lock(result["batch_name"])
        return result

    monkeypatch.setattr(bulk_import, "materialise_folder", flaky)
    run = _run_to_completion(run_id)

    assert run["status"] == STATUS_FAILED
    assert run["folders"][1]["status"] == FOLDER_FAILED
    assert run["folders"][2]["status"] == FOLDER_PENDING, "run must stop, not continue"


# --------------------------------------------------------------------------- #
# Pause / cancel
# --------------------------------------------------------------------------- #
def test_cancel_keeps_completed_data(import_root, runs_dir, template, monkeypatch):
    run_id = _create_run(template)["bulk_run_id"]

    def fake(image_path, *a, **k):
        # Cancel as soon as the first folder starts producing results.
        bulk_orchestrator.request_cancel(run_id)
        return {"fields": {"Komponist": "Bach"}}, None

    monkeypatch.setattr(ocr_engine, "_call_vlm_api_resilient", fake)
    run = _run_to_completion(run_id)

    assert run["status"] == STATUS_CANCELLED
    # Whatever completed is kept, and the folder stays resumable.
    first = run["folders"][0]
    assert first["status"] == FOLDER_PENDING
    results, _ = read_checkpoint(
        batch_manager.get_batch_path(first["batch_name"]) / "checkpoint.json"
    )
    assert len(results) >= 1
    assert run["folders"][2]["batch_name"] is None, "later folders were not started"


def test_cancel_does_not_delete_batch_data(import_root, runs_dir, template, monkeypatch):
    run_id = _create_run(template)["bulk_run_id"]

    def cancelling(image_path, *a, **k):
        bulk_orchestrator.request_cancel(run_id)
        return {"fields": {"Komponist": "Bach"}}, None

    monkeypatch.setattr(ocr_engine, "_call_vlm_api_resilient", cancelling)
    run = _run_to_completion(run_id)

    assert run["status"] == STATUS_CANCELLED
    assert batch_manager.get_batch_path(run["folders"][0]["batch_name"]).exists()


def test_pause_then_resume_completes_without_reprocessing(
    import_root, runs_dir, template, monkeypatch
):
    """The guarantee is checkpoint-based: an image recorded as successful is
    never sent to the model again.

    Note this is NOT the same as "every image is sent at most once". Cancellation
    is cooperative and the batch engine keeps up to MAX_WORKERS cards in flight,
    so cards whose result had not yet been collected when the pause landed are
    discarded and re-processed on resume. That is the existing single-batch
    cancel semantics, unchanged here — see the known limitations in the plan.
    """
    run_id = _create_run(template)["bulk_run_id"]
    seen: list = []

    def pausing(image_path, *a, **k):
        seen.append(image_path.name)
        bulk_orchestrator.request_pause(run_id)
        return {"fields": {"Komponist": "Bach"}}, None

    monkeypatch.setattr(ocr_engine, "_call_vlm_api_resilient", pausing)
    run = _run_to_completion(run_id)
    assert run["status"] == STATUS_PAUSED
    assert run["completed_at"] is None

    # Everything the checkpoints already record as successful at pause time.
    done_at_pause = set()
    for folder in run["folders"]:
        if not folder["batch_name"]:
            continue
        cp = batch_manager.get_batch_path(folder["batch_name"]) / "checkpoint.json"
        if cp.exists():
            results, _ = read_checkpoint(cp)
            done_at_pause |= {r["filename"] for r in results if r.get("success") is True}
    assert done_at_pause, "the pause must preserve the results already produced"

    seen.clear()

    def normal(image_path, *a, **k):
        seen.append(image_path.name)
        return {"fields": {"Komponist": "Bach"}}, None

    monkeypatch.setattr(ocr_engine, "_call_vlm_api_resilient", normal)
    run = _run_to_completion(run_id)

    assert run["status"] == STATUS_COMPLETED
    assert run["images_processed"] == 6
    assert run["folders_completed"] == 3
    assert done_at_pause.isdisjoint(seen), (
        f"already-successful images were re-sent to the model: "
        f"{done_at_pause.intersection(seen)}"
    )


def test_pause_and_cancel_on_unknown_run(runs_dir):
    assert bulk_orchestrator.request_pause("11111111-1111-1111-1111-111111111111") is False
    assert bulk_orchestrator.request_cancel("nope") is False


# --------------------------------------------------------------------------- #
# Single-run lock
# --------------------------------------------------------------------------- #
def test_second_concurrent_run_is_refused(import_root, runs_dir, template, calls):
    first = _create_run(template)["bulk_run_id"]
    second = _create_run(template)["bulk_run_id"]

    async def go():
        await bulk_orchestrator.start_run(first)
        with pytest.raises(RuntimeError):
            await bulk_orchestrator.start_run(second)
        await bulk_orchestrator._tasks[first]

    asyncio.run(go())
    assert bulk_manager.get_run(second)["status"] == "queued"


def test_lock_is_released_after_a_run_finishes(import_root, runs_dir, template, calls):
    _run_to_completion(_create_run(template)["bulk_run_id"])
    assert bulk_manager.is_any_run_active() is False


def test_lock_is_released_after_a_structural_failure(
    import_root, runs_dir, template, monkeypatch
):
    monkeypatch.setattr(
        ocr_engine, "_call_vlm_api_resilient", lambda *a, **k: (None, "HTTP 500")
    )
    _run_to_completion(_create_run(template)["bulk_run_id"])
    assert bulk_manager.is_any_run_active() is False


def test_start_unknown_run_raises(runs_dir):
    async def go():
        with pytest.raises(LookupError):
            await bulk_orchestrator.start_run("11111111-1111-1111-1111-111111111111")

    asyncio.run(go())


# --------------------------------------------------------------------------- #
# Stale per-batch lock after a crash
# --------------------------------------------------------------------------- #
def test_resume_releases_the_stale_batch_lock(import_root, runs_dir, template, calls):
    """A process killed mid-batch never runs run_ocr_task's finally block, so the
    batch keeps its .run.lock. Left in place, Resume cannot re-acquire it and
    would mark the interrupted folder failed — the very folder Resume exists to
    finish. The startup hook must release it."""
    run_id = _create_run(template)["bulk_run_id"]
    batch = bulk_import.materialise_folder("Batch_001", fields=FIELDS)["batch_name"]

    # Simulate the crash: folder mid-flight, batch lock held, no process to free it.
    assert batch_manager.acquire_batch_lock(batch) is True
    bulk_manager.update_folder(run_id, "Batch_001", batch_name=batch, status="running")
    bulk_manager.update_run(run_id, status=STATUS_RUNNING, current_folder="Batch_001",
                            current_batch_id=batch)

    # ── restart ──
    assert bulk_manager.mark_interrupted_runs() == [run_id]
    assert batch_manager.is_run_active(batch) is False, "stale batch lock must be released"

    # ── Resume finishes the interrupted folder rather than failing it ──
    run = _run_to_completion(run_id)

    assert run["status"] == STATUS_COMPLETED
    assert run["folders"][0]["status"] == FOLDER_COMPLETED
    assert run["folders_completed"] == 3
    assert run["images_processed"] == 6


def test_startup_leaves_unrelated_batch_locks_alone(import_root, runs_dir, template):
    """Only the batch a bulk run recorded as current is unlocked. Sweeping every
    lock would change the interactive workflow's behaviour."""
    run_id = _create_run(template)["bulk_run_id"]
    mine = bulk_import.materialise_folder("Batch_001", fields=FIELDS)["batch_name"]
    other = bulk_import.materialise_folder("Batch_002", fields=FIELDS)["batch_name"]
    batch_manager.acquire_batch_lock(mine)
    batch_manager.acquire_batch_lock(other)
    bulk_manager.update_run(run_id, status=STATUS_RUNNING, current_batch_id=mine)

    bulk_manager.mark_interrupted_runs()

    assert batch_manager.is_run_active(mine) is False
    assert batch_manager.is_run_active(other) is True, "unrelated lock must be untouched"
    batch_manager.release_batch_lock(other)
