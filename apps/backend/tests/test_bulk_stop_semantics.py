"""Pause and cancel: what stops, when, and what an operator can see.

The observed failure was not that stopping did not work — it was that it was
invisible and slow. The audit log of the 2026-09-08 AMIGA run shows Cancel
clicked at 06:16:43, clicked again 92 s later because nothing had changed, and
the run only finalising at 06:19:23. Two causes:

* ``_request_stop`` set the flag but never broadcast it, and the UI prefers the
  pushed state over the HTTP response — so the last state on the wire still
  said ``pause_requested: false`` until the next image finished.
* the engine's retry loop did not know about the cancel event, so a stop could
  still be followed by a *new* request and had a worst case of
  ``MAX_WORKERS × MAX_RETRIES × VLM_REQUEST_TIMEOUT_SECONDS``.

Both are asserted here, together with the invariant that matters for 14,000
cards: a card pre-empted by a stop is left untouched, so a resume processes it
normally instead of finding it recorded as a permanent failure.

Every VLM call is intercepted. No provider is contacted.
"""
import asyncio
import json
import threading

import pytest

from app.core.checkpoint import read_checkpoint
from app.core.config import settings
from app.models.schemas import TemplateCreate
from app.services import bulk_export, bulk_import, bulk_orchestrator
from app.services import ocr_engine as engine_module
from app.services.batch_manager import BatchMissingError, batch_manager
from app.services.bulk_manager import (
    FOLDER_PENDING,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_PAUSED,
    bulk_manager,
)
from app.services.bulk_progress import bulk_channel
from app.services.ocr_engine import ocr_engine
from app.services.template_service import template_service
from app.services.ws_manager import ws_manager

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16 + b"\xff\xd9"
FIELDS = ["Komponist", "Signatur"]
CARDS = 8


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _single_worker_no_waiting(monkeypatch):
    """One card at a time and no backoff — the operator's own configuration."""
    monkeypatch.setattr(settings, "MAX_WORKERS", 1)
    monkeypatch.setattr(settings, "MAX_RETRIES", 2)
    monkeypatch.setattr(settings, "OLLAMA_API_KEY", "test-key-not-used")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "test-key-not-used")
    monkeypatch.setattr(engine_module, "_MODEL_RETRY_DELAY_SECONDS", 0.0)
    monkeypatch.setattr(engine_module.time, "sleep", lambda _s: None)


@pytest.fixture(autouse=True)
def _clean_state():
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
    root = tmp_path / "amiga"
    folder = root / "Batch_001"
    folder.mkdir(parents=True)
    for i in range(CARDS):
        (folder / f"IMG_{i:03d}.JPG").write_bytes(JPEG)
    monkeypatch.setattr(settings, "BULK_IMPORT_ROOT", str(root))
    return root


@pytest.fixture
def runs_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(bulk_manager, "runs_dir", tmp_path / "bulk_runs")
    return bulk_manager.runs_dir


@pytest.fixture
def template():
    tpl = template_service.create_template(TemplateCreate(name="Stop probe", fields=FIELDS))
    yield tpl
    template_service.delete_template(tpl.id)


class _Resp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload or {}
        self.text = json.dumps(self._payload)
        self.headers: dict = {}

    def json(self):
        return self._payload


def _ok():
    content = json.dumps({"fields": {"Komponist": "Bach", "Signatur": "Spez. 1"}})
    return _Resp(200, {"choices": [{"message": {"content": content}, "finish_reason": "stop"}]})


def _create_run(template):
    return bulk_manager.create_run(
        name="Stop probe", template_id=template.id, schema_fields=FIELDS,
        provider="ollama", model="qwen3-vl:32b",
        folders=[{"source_folder": "Batch_001", "images_total": CARDS}],
    )


def _drive(run_id):
    async def go():
        await bulk_orchestrator.start_run(run_id)
        await bulk_orchestrator._tasks[run_id]

    asyncio.run(go())
    return bulk_manager.get_run(run_id)


def _stopping_transport(monkeypatch, run_id, *, pause: bool, after: int = 2):
    """Answer normally, and request a stop while card *after* is in flight."""
    posts: list = []

    def fake_post(url, headers=None, json=None, **kw):
        posts.append(url)
        if len(posts) == after:
            if pause:
                bulk_orchestrator.request_pause(run_id)
            else:
                bulk_orchestrator.request_cancel(run_id)
        return _ok()

    monkeypatch.setattr(ocr_engine.session, "post", fake_post)
    return posts


# --------------------------------------------------------------------------- #
# 19 + 21 — pause while a card is in flight
# --------------------------------------------------------------------------- #
def test_pause_during_a_running_card_finishes_it_and_starts_no_other(
    import_root, runs_dir, template, monkeypatch
):
    run_id = _create_run(template)["bulk_run_id"]
    posts = _stopping_transport(monkeypatch, run_id, pause=True, after=2)

    run = _drive(run_id)

    assert run["status"] == STATUS_PAUSED
    # The card in flight when the pause landed is allowed to finish; nothing
    # after it may be sent.
    assert len(posts) == 2, f"a card was started after the pause ({len(posts)} requests)"
    assert run["images_processed"] == 2


def test_paused_run_leaves_the_folder_resumable(import_root, runs_dir, template, monkeypatch):
    run_id = _create_run(template)["bulk_run_id"]
    _stopping_transport(monkeypatch, run_id, pause=True, after=2)

    run = _drive(run_id)

    assert run["folders"][0]["status"] == FOLDER_PENDING
    assert run["pause_requested"] is False, "the request must not survive into the resume"


# --------------------------------------------------------------------------- #
# 20 — pause between cards
# --------------------------------------------------------------------------- #
def test_pause_between_cards_stops_before_the_next_one(
    import_root, runs_dir, template, monkeypatch
):
    """The stop lands after a card's checkpoint is written, before the next
    request. It must be honoured without sending anything further."""
    run_id = _create_run(template)["bulk_run_id"]
    posts: list = []

    def fake_post(url, headers=None, json=None, **kw):
        posts.append(url)
        return _ok()

    monkeypatch.setattr(ocr_engine.session, "post", fake_post)

    async def go():
        await bulk_orchestrator.start_run(run_id)
        # Request the pause before the driver has issued a single request, i.e.
        # cleanly between cards.
        bulk_orchestrator.request_pause(run_id)
        await bulk_orchestrator._tasks[run_id]

    asyncio.run(go())
    run = bulk_manager.get_run(run_id)

    assert run["status"] == STATUS_PAUSED
    assert len(posts) <= 1, f"{len(posts)} cards were sent after a pause between cards"


# --------------------------------------------------------------------------- #
# 22 + 23 — checkpoint survives, resume does not reprocess
# --------------------------------------------------------------------------- #
def test_pause_keeps_the_checkpoint_and_resume_processes_each_card_once(
    import_root, runs_dir, template, monkeypatch
):
    run_id = _create_run(template)["bulk_run_id"]
    _stopping_transport(monkeypatch, run_id, pause=True, after=2)
    paused = _drive(run_id)

    batch = paused["folders"][0]["batch_name"]
    results, _ = read_checkpoint(batch_manager.get_batch_path(batch) / "checkpoint.json")
    done_at_pause = {r["filename"] for r in results if r.get("success") is True}
    assert done_at_pause, "the pause must preserve what was already extracted"

    # Resume with a transport that records every filename it is asked for.
    sent: list = []

    def recording_post(url, headers=None, json=None, **kw):
        sent.append(url)
        return _ok()

    monkeypatch.setattr(ocr_engine.session, "post", recording_post)
    resumed = _drive(run_id)

    assert resumed["status"] == STATUS_COMPLETED
    # Exactly the cards that were still outstanding, no more.
    assert len(sent) == CARDS - len(done_at_pause)

    final, _ = read_checkpoint(batch_manager.get_batch_path(batch) / "checkpoint.json")
    filenames = [r["filename"] for r in final]
    assert len(filenames) == len(set(filenames)) == CARDS, "a card was processed twice"


# --------------------------------------------------------------------------- #
# 24–28 — cancel
# --------------------------------------------------------------------------- #
def test_cancel_during_a_running_card_starts_no_other(
    import_root, runs_dir, template, monkeypatch
):
    run_id = _create_run(template)["bulk_run_id"]
    posts = _stopping_transport(monkeypatch, run_id, pause=False, after=2)

    run = _drive(run_id)

    assert run["status"] == STATUS_CANCELLED
    assert len(posts) == 2, f"a card was started after the cancel ({len(posts)} requests)"


def test_cancel_between_cards_stops_before_the_next_one(
    import_root, runs_dir, template, monkeypatch
):
    run_id = _create_run(template)["bulk_run_id"]
    posts: list = []
    monkeypatch.setattr(
        ocr_engine.session, "post",
        lambda url, headers=None, json=None, **kw: (posts.append(url), _ok())[1],
    )

    async def go():
        await bulk_orchestrator.start_run(run_id)
        bulk_orchestrator.request_cancel(run_id)
        await bulk_orchestrator._tasks[run_id]

    asyncio.run(go())
    run = bulk_manager.get_run(run_id)

    assert run["status"] == STATUS_CANCELLED
    assert len(posts) <= 1


def test_cancel_keeps_completed_results_and_they_still_export(
    import_root, runs_dir, template, monkeypatch
):
    run_id = _create_run(template)["bulk_run_id"]
    _stopping_transport(monkeypatch, run_id, pause=False, after=3)

    run = _drive(run_id)
    assert run["status"] == STATUS_CANCELLED
    assert run["images_processed"] == 3

    batch = run["folders"][0]["batch_name"]
    results, _ = read_checkpoint(batch_manager.get_batch_path(batch) / "checkpoint.json")
    assert len([r for r in results if r.get("success") is True]) == 3

    # Export after a cancel: the consolidated CSV must carry those rows.
    target = runs_dir / run_id / "consolidated.csv"
    bulk_export.write_consolidated_csv(run, target)
    body = target.read_text(encoding="utf-8")
    data_rows = [line for line in body.splitlines() if "IMG_" in line]
    assert len(data_rows) == 3, "every extracted card must survive the cancel in the export"
    rows, _failures = bulk_export.row_counts(run)
    assert rows == 3


def test_a_card_preempted_by_a_stop_is_not_recorded_as_failed(
    import_root, runs_dir, template, monkeypatch
):
    """The invariant that protects a 14,000-card run.

    A card the stop caught before it reached the model was never processed. If
    it were written to the checkpoint as a failure it would also be moved to
    _errors/, and a resume would silently skip it — only a manual per-image
    retry could ever bring it back.
    """
    run_id = _create_run(template)["bulk_run_id"]
    _stopping_transport(monkeypatch, run_id, pause=False, after=2)

    run = _drive(run_id)

    batch = run["folders"][0]["batch_name"]
    batch_path = batch_manager.get_batch_path(batch)
    results, _ = read_checkpoint(batch_path / "checkpoint.json")

    assert [r for r in results if r.get("success") is not True] == []
    assert run["images_failed"] == 0
    error_dir = batch_path / "_errors"
    assert not error_dir.exists() or not any(error_dir.iterdir())
    # And every card is still available to a resume.
    remaining = [p.name for p in batch_path.iterdir() if p.suffix.upper() == ".JPG"]
    assert len(remaining) == CARDS


# --------------------------------------------------------------------------- #
# The stop is visible immediately (the "spinner keeps spinning" bug)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "request_stop,field",
    [
        (bulk_orchestrator.request_pause, "pause_requested"),
        (bulk_orchestrator.request_cancel, "cancel_requested"),
    ],
)
def test_requesting_a_stop_broadcasts_it_at_once(runs_dir, template, request_stop, field):
    """Without this the last state on the wire kept saying the run was simply
    running, for as long as the current card took — minutes."""
    run = bulk_manager.create_run(
        name="Stop probe", template_id=template.id, schema_fields=FIELDS,
        provider="ollama", model="qwen3-vl:32b",
        folders=[{"source_folder": "Batch_001", "images_total": CARDS}],
    )
    run_id = run["bulk_run_id"]
    channel = bulk_channel(run_id)
    ws_manager.bulk_states.pop(channel, None)

    assert request_stop(run_id) is True

    published = ws_manager.bulk_states.get(channel)
    assert published is not None, "the stop request published nothing"
    assert getattr(published, field) is True


def test_pause_and_cancel_on_unknown_run_publish_nothing(runs_dir):
    assert bulk_orchestrator.request_pause("11111111-1111-1111-1111-111111111111") is False
    assert bulk_orchestrator.request_cancel("nope") is False


# --------------------------------------------------------------------------- #
# The engine issues no further request once a stop is registered
# --------------------------------------------------------------------------- #
def test_the_engine_does_not_retry_after_a_stop(tmp_path, monkeypatch):
    """A retry is a NEW request. The retry loop used to be unaware of the stop,
    which is why a pause could take MAX_RETRIES × timeout to be felt."""
    card = tmp_path / "IMG_001.JPG"
    card.write_bytes(JPEG)
    cancel_event = threading.Event()
    posts: list = []

    def fake_post(url, headers=None, json=None, **kw):
        posts.append(url)
        cancel_event.set()          # a stop lands while this request is open
        return _Resp(200, {"choices": [{"message": {"content": ""},
                                        "finish_reason": "stop"}]})

    monkeypatch.setattr(ocr_engine.session, "post", fake_post)

    _parsed, error = ocr_engine._call_vlm_api_resilient(
        card, fields=FIELDS, api_endpoint=settings.OLLAMA_API_ENDPOINT,
        model_name="qwen3-vl:32b", api_key="test-key-not-used",
        cancel_event=cancel_event,
    )

    assert len(posts) == 1, "an empty response was retried despite a registered stop"
    assert error == engine_module.ERROR_STOP_REQUESTED


def test_a_stop_before_the_first_request_sends_nothing(tmp_path, monkeypatch):
    card = tmp_path / "IMG_001.JPG"
    card.write_bytes(JPEG)
    cancel_event = threading.Event()
    cancel_event.set()
    posts: list = []
    monkeypatch.setattr(
        ocr_engine.session, "post",
        lambda url, headers=None, json=None, **kw: (posts.append(url), _ok())[1],
    )

    result = ocr_engine._process_card_sync(
        card, "batch", FIELDS, api_endpoint=settings.OLLAMA_API_ENDPOINT,
        model_name="qwen3-vl:32b", api_key="test-key-not-used",
        cancel_event=cancel_event,
    )

    assert posts == []
    assert result["stopped"] is True
    assert result["success"] is False


# --------------------------------------------------------------------------- #
# 29 — cancelling a batch that is not running says so
# --------------------------------------------------------------------------- #
def test_cancelling_an_idle_batch_reports_that_nothing_was_cancelled(client, monkeypatch):
    """The log line 'No cancel event found for batch … — nothing to cancel'
    came with an HTTP 200 reading 'Cancel requested', so the UI believed a
    cancellation had happened."""
    monkeypatch.setattr(settings, "BATCHES_DIR", settings.BATCHES_DIR)
    ws_manager.clear_cancel_event("Some_Batch_deadbeef")

    response = client.post("/api/v1/batches/Some_Batch_deadbeef/cancel")

    assert response.status_code == 200
    body = response.json()
    assert body["cancelled"] is False
    assert "nothing to cancel" in body["message"].lower()


def test_cancelling_a_running_batch_reports_success(client):
    ws_manager.get_or_create_cancel_event("Some_Batch_running")
    try:
        response = client.post("/api/v1/batches/Some_Batch_running/cancel")

        assert response.json()["cancelled"] is True
        assert ws_manager.cancel_events["Some_Batch_running"].is_set()
    finally:
        ws_manager.clear_cancel_event("Some_Batch_running")


# --------------------------------------------------------------------------- #
# 36 — a batch directory that no longer exists
# --------------------------------------------------------------------------- #
def test_locking_a_missing_batch_raises_a_named_error_not_an_errno():
    with pytest.raises(BatchMissingError) as excinfo:
        batch_manager.acquire_batch_lock("Vanished_Batch_00000000")

    message = str(excinfo.value)
    assert "no longer exists" in message
    assert "re-import" in message
    assert ".run.lock" not in message, "the lockfile path is an implementation detail"


def test_locking_a_missing_batch_is_not_reported_as_already_locked():
    """A False return means "someone else holds the lock". A vanished batch is
    a different fault and must not be mistaken for it."""
    with pytest.raises(BatchMissingError):
        batch_manager.acquire_batch_lock("Vanished_Batch_11111111")


def test_a_vanished_batch_fails_the_run_with_a_readable_message(
    import_root, runs_dir, template, monkeypatch
):
    """The exact failure that killed the qwen3-vl:235b run before its first
    inference, with `[Errno 2] … /.run.lock` persisted into run.json."""
    run = _create_run(template)
    run_id = run["bulk_run_id"]

    # Materialise the folder, then delete the batch underneath the run.
    imported = bulk_import.materialise_folder("Batch_001", fields=FIELDS)
    bulk_manager.update_folder(
        run_id, "Batch_001", batch_name=imported["batch_name"],
        images_total=imported["images_total"],
    )
    batch_manager.delete_batch(imported["batch_name"])

    posts: list = []
    monkeypatch.setattr(
        ocr_engine.session, "post",
        lambda url, headers=None, json=None, **kw: (posts.append(url), _ok())[1],
    )

    final = _drive(run_id)

    assert final["status"] == "failed"
    assert "no longer exists" in (final["error"] or "")
    assert "Errno" not in (final["error"] or "")
    assert ".run.lock" not in (final["error"] or "")
    assert posts == [], "nothing may be sent to the model for a vanished batch"
