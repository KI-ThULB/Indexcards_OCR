"""SAR-04d: deterministic production Bulk gate and lifecycle interleavings."""
import asyncio
import copy
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, Mock

import pytest

from app.core import transactions
from app.core.checkpoint import CheckpointError, write_checkpoint
from app.core.transactions import TransactionTimeout
from app.services import bulk_orchestrator as bulk
from app.services.batch_manager import batch_manager
from app.services.bulk_manager import bulk_manager, BulkStateError, BulkRevisionConflict
from test_error_disclosure import SECRET, assert_safe, make_run
from test_error_disclosure import isolated_state as isolated_state


@pytest.fixture(autouse=True)
def task_state(monkeypatch):
    monkeypatch.setattr(bulk, "_tasks", {})
    monkeypatch.setattr(bulk, "_cancel_targets", {})


@pytest.fixture
def run():
    value = make_run()
    return bulk_manager.update_run(value["bulk_run_id"], status="running")


def contention(monkeypatch):
    event = threading.Event()
    original = transactions.fcntl.flock
    def flock(fd, flags):
        try:
            return original(fd, flags)
        except BlockingIOError:
            event.set()
            raise
    monkeypatch.setattr(transactions.fcntl, "flock", flock)
    return event


def associated(run):
    path = batch_manager.batches_dir / "associated"
    path.mkdir()
    write_checkpoint(path / "checkpoint.json", [], [])
    return path, bulk_manager.update_folder(run["bulk_run_id"], "folder", batch_name=path.name, status="running")


@pytest.mark.parametrize("flag", ["pause_requested", "cancel_requested"])
def test_parallel_bulk_mutations_preserve_flags_and_counts(run, monkeypatch, flag):
    rid = run["bulk_run_id"]
    entered, release = threading.Event(), threading.Event()
    contended = contention(monkeypatch)
    def stop(current):
        entered.set()
        assert release.wait(5)
        current[flag] = True
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(bulk_manager.mutate, rid, stop)
        assert entered.wait(5)
        second = pool.submit(bulk_manager.update_folder, rid, "folder", images_processed=1)
        try:
            assert contended.wait(5) and not second.done()
        finally:
            release.set()
        first.result(5)
        second.result(5)
    value = bulk_manager.get_run(rid)
    assert value[flag] and value["images_processed"] == 1


@pytest.mark.parametrize("drop_folders", [False, True])
def test_stale_complete_projection_rejected(run, drop_folders):
    stale = copy.deepcopy(run)
    bulk_manager.update_run(run["bulk_run_id"], pause_requested=True)
    original = bulk_manager._run_json(run["bulk_run_id"]).read_bytes()
    stale["status"] = "completed"
    if drop_folders:
        stale["folders"] = []
    with pytest.raises(BulkRevisionConflict):
        bulk_manager.save_run(stale)
    assert bulk_manager._run_json(run["bulk_run_id"]).read_bytes() == original
    assert bulk_manager.get_run(run["bulk_run_id"])["pause_requested"]


@pytest.mark.parametrize("stop", ["pause", "cancel"])
def test_reconcile_competes_with_stop_on_fresh_state(run, monkeypatch, stop):
    path, _ = associated(run)
    write_checkpoint(path / "checkpoint.json", [{"filename":"one.jpg", "success":True}], [])
    entered, release = threading.Event(), threading.Event()
    real = bulk._reconcile_counts
    contended = contention(monkeypatch)
    def reconcile(current):
        entered.set()
        assert release.wait(5)
        return real(current)
    monkeypatch.setattr(bulk, "_reconcile_counts", reconcile)
    request = bulk.request_pause if stop == "pause" else bulk.request_cancel
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(bulk._refresh_and_emit, run["bulk_run_id"])
        assert entered.wait(5)
        second = pool.submit(request, run["bulk_run_id"])
        try:
            assert contended.wait(5)
        finally:
            release.set()
        first.result(5)
        assert second.result(5)
    value = bulk_manager.get_run(run["bulk_run_id"])
    assert value[stop+"_requested"] and value["images_processed"] == 1


def test_reconcile_joins_batch_snapshot_after_writer(run, monkeypatch):
    path, _ = associated(run)
    entered, release = threading.Event(), threading.Event()
    contended = contention(monkeypatch)
    def write():
        entered.set()
        assert release.wait(5)
        write_checkpoint(path / "checkpoint.json", [{"filename":"done.jpg", "success":True}], [])
    with ThreadPoolExecutor(2) as pool:
        writer = pool.submit(batch_manager.run_batch_sync, path, write)
        assert entered.wait(5)
        reconcile = pool.submit(bulk._refresh_and_emit, run["bulk_run_id"])
        try:
            assert contended.wait(5) and not reconcile.done()
        finally:
            release.set()
        writer.result(5)
        reconcile.result(5)
    assert bulk_manager.get_run(run["bulk_run_id"])["images_processed"] == 1


def test_concurrent_resume_only_one_driver(monkeypatch):
    value = make_run()
    rid = value["bulk_run_id"]
    bulk_manager.update_run(rid, status="paused")
    entered, finish = asyncio.Event(), asyncio.Event()
    calls = []
    async def drive(_):
        calls.append(rid)
        entered.set()
        await finish.wait()
        await bulk._call(bulk._finalise, rid, "completed")
    monkeypatch.setattr(bulk, "_drive_folders", drive)
    async def scenario():
        results = await asyncio.gather(bulk.start_run(rid), bulk.start_run(rid), return_exceptions=True)
        assert sum(isinstance(value, dict) for value in results) == 1
        assert sum(isinstance(value, RuntimeError) for value in results) == 1
        await entered.wait()
        assert calls == [rid] and bulk_manager.is_any_run_active()
        task = bulk._tasks[rid]
        finish.set()
        await task
        assert not bulk_manager.is_any_run_active()
    asyncio.run(scenario())


def test_cancel_admitted_start_joins_and_releases_own_claim(monkeypatch):
    value = make_run()
    rid = value["bulk_run_id"]
    entered, release = threading.Event(), threading.Event()
    real = bulk_manager._persist_run
    def persist(current):
        if current["status"] == "running":
            entered.set()
            assert release.wait(5)
        return real(current)
    monkeypatch.setattr(bulk_manager, "_persist_run", persist)
    driver = AsyncMock()
    monkeypatch.setattr(bulk, "_drive", driver)
    async def scenario():
        task = asyncio.create_task(bulk.start_run(rid))
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            for _ in range(2):
                task.cancel()
                await asyncio.sleep(0)
                assert not task.done() and bulk_manager.is_any_run_active()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not bulk_manager.is_any_run_active() and not bulk._tasks
    asyncio.run(scenario())
    driver.assert_not_called()
    assert bulk_manager.get_run(rid)["status"] == "interrupted"


def test_gate_wait_does_not_block_event_loop(run, monkeypatch):
    rid = run["bulk_run_id"]
    entered, release = threading.Event(), threading.Event()
    contended = contention(monkeypatch)
    def hold(current):
        entered.set()
        assert release.wait(5)
    async def scenario():
        with ThreadPoolExecutor(1) as pool:
            holder = pool.submit(bulk_manager.mutate, rid, hold)
            assert await asyncio.to_thread(entered.wait, 3)
            task = asyncio.create_task(bulk_manager.mutate_async(rid, lambda current: current.update(pause_requested=True)))
            assert await asyncio.to_thread(contended.wait, 3)
            heartbeat = asyncio.Event()
            asyncio.get_running_loop().call_soon(heartbeat.set)
            try:
                await asyncio.wait_for(heartbeat.wait(), 1)
            finally:
                release.set()
            await task
            holder.result(5)
    asyncio.run(scenario())
    assert bulk_manager.get_run(rid)["pause_requested"]


@pytest.mark.parametrize("fault", ["json", "structure", "unreadable", "write"])
def test_bulk_metadata_errors_are_strict_and_safe(run, monkeypatch, caplog, fault):
    from pathlib import Path
    import app.services.bulk_manager as module
    path = bulk_manager._run_json(run["bulk_run_id"])
    real_read = Path.read_bytes
    if fault == "json":
        path.write_text('{'+SECRET)
    elif fault == "structure":
        path.write_text(json.dumps({"bulk_run_id":run["bulk_run_id"], "status":"running", "folders":{}}))
    elif fault == "unreadable":
        def read(self):
            if self == path:
                raise PermissionError(SECRET)
            return real_read(self)
        monkeypatch.setattr(Path, "read_bytes", read)
    else:
        monkeypatch.setattr(module, "atomic_write_json", Mock(side_effect=OSError(SECRET)))
    original = real_read(path)
    with pytest.raises(BulkStateError) as error:
        bulk_manager.update_run(run["bulk_run_id"], pause_requested=True)
    assert real_read(path) == original
    assert_safe(caplog, error.value)


@pytest.mark.parametrize("stop", ["pause", "cancel"])
def test_finalise_consumes_latest_stop_without_losing_latch(run, stop):
    rid = run["bulk_run_id"]
    bulk_manager.update_run(rid, **{stop+"_requested":True})
    bulk._finalise(rid, "completed")
    bulk_manager.update_run(rid, pause_requested=False, cancel_requested=False)
    bulk_manager.update_folder(rid, "folder", status="running", images_processed=99)
    value = bulk_manager.get_run(rid)
    assert value["status"] == ("paused" if stop == "pause" else "cancelled")
    assert value[stop+"_requested"] and value["images_processed"] == 0


def test_resume_preserves_integrity_marker_and_never_plans(run, monkeypatch):
    path, _ = associated(run)
    rid = run["bulk_run_id"]
    bulk_manager.update_folder(rid, "folder", integrity_error="checkpoint_invalid")
    driver = AsyncMock()
    monkeypatch.setattr(bulk, "_drive", driver)
    with pytest.raises(CheckpointError):
        asyncio.run(bulk.start_run(rid))
    value = bulk_manager.get_run(rid)
    assert value["checkpoint_error"] and value["folders"][0]["integrity_error"] == "checkpoint_invalid"
    assert not bulk_manager.is_any_run_active()
    driver.assert_not_called()


def test_uuid_case_alias_shares_bulk_identity(run):
    rid = run["bulk_run_id"]
    assert bulk_manager._resources(rid) == bulk_manager._resources(rid.upper())
    bulk_manager.update_run(rid.upper(), pause_requested=True)
    assert bulk_manager.get_run(rid)["pause_requested"]


def test_old_stop_event_cannot_cancel_new_batch_run(run):
    from app.services.ws_manager import ws_manager
    old = threading.Event()
    bulk._cancel_targets[run["bulk_run_id"]] = ("associated", old)
    new = ws_manager.get_or_create_cancel_event("associated")
    assert bulk.request_cancel(run["bulk_run_id"])
    assert old.is_set() and not new.is_set()


def test_bulk_timeout_has_no_mutation(run, monkeypatch, caplog):
    rid = run["bulk_run_id"]
    original = bulk_manager._run_json(rid).read_bytes()
    coordinator = batch_manager._registry_coordinator()
    entered, release = threading.Event(), threading.Event()
    def hold(current):
        entered.set()
        assert release.wait(5)
    async def scenario():
        with ThreadPoolExecutor(1) as pool:
            holder = pool.submit(bulk_manager.mutate, rid, hold)
            assert await asyncio.to_thread(entered.wait, 3)
            coordinator.timeout = 0
            monkeypatch.setattr(batch_manager, "_registry_coordinator", lambda: coordinator)
            try:
                with pytest.raises(TransactionTimeout) as error:
                    await bulk_manager.mutate_async(rid, lambda current: current.update(cancel_requested=True))
                assert_safe(caplog, error.value)
            finally:
                release.set()
            holder.result(5)
    asyncio.run(scenario())
    assert bulk_manager._run_json(rid).read_bytes() == original


def test_different_bulk_runs_are_independent(run):
    other = make_run()
    entered, release = threading.Event(), threading.Event()
    def hold(current):
        entered.set()
        assert release.wait(5)
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(bulk_manager.mutate, run["bulk_run_id"], hold)
        assert entered.wait(5)
        try:
            second = pool.submit(bulk_manager.update_run, other["bulk_run_id"], name="changed")
            assert second.result(2)["name"] == "changed"
        finally:
            release.set()
        first.result(5)


def test_start_write_failure_never_schedules_or_leaks_claim(monkeypatch, caplog):
    import app.services.bulk_manager as module
    value = make_run()
    path = bulk_manager._run_json(value["bulk_run_id"])
    before = path.read_bytes()
    driver = AsyncMock()
    monkeypatch.setattr(bulk, "_drive", driver)
    monkeypatch.setattr(module, "atomic_write_json", Mock(side_effect=OSError(SECRET)))
    with pytest.raises(BulkStateError) as error:
        asyncio.run(bulk.start_run(value["bulk_run_id"]))
    assert path.read_bytes() == before and not bulk_manager.is_any_run_active()
    assert not bulk._tasks
    driver.assert_not_called()
    assert_safe(caplog, error.value)


def test_new_attempt_publishes_running_over_old_terminal_state(run, monkeypatch, tmp_path):
    from app.api.api_v1.endpoints import batches
    from app.core.config import settings
    from app.models.schemas import BatchProgress
    from app.services.ocr_engine import ocr_engine
    from app.services.ws_manager import ws_manager
    path, _ = associated(run)
    monkeypatch.setattr(settings, "BATCHES_HISTORY_FILE", str(tmp_path / "history.json"))
    batch_manager._record_history(path.name, "Associated")
    (path / "config.json").write_text('{"provider":"ollama","fields":["field"]}')
    monkeypatch.setattr(batches, "_resolve_provider", lambda *_: ("unused", "mock", None))
    ws_manager.batch_states[path.name] = BatchProgress(batch_name=path.name, current=1, total=1, percentage=100, status="completed")
    real_broadcast = ws_manager.broadcast_progress
    events = []
    async def broadcast(name, progress):
        events.append(progress.status)
        await real_broadcast(name, progress)
    async def process(**kwargs):
        write_checkpoint(path / "checkpoint.json", [{"filename":"done.jpg", "success":True}], [])
        await kwargs["progress_callback"](path.name, BatchProgress(batch_name=path.name, current=1, total=1, percentage=100, status="running"))
    monkeypatch.setattr(ocr_engine, "process_batch", process)
    monkeypatch.setattr(ws_manager, "broadcast_progress", broadcast)
    asyncio.run(bulk._process_folder(run["bulk_run_id"], 0))
    assert events == ["running", "completed"]
    assert not batch_manager.is_run_active(path.name)


def test_changed_association_aborts_before_batch_reservation(run, monkeypatch):
    from app.api.api_v1.endpoints import batches
    path, _ = associated(run)
    original = bulk_manager.mutate_async
    job = AsyncMock()
    monkeypatch.setattr(batches, "run_ocr_task", job)
    async def changed(*args, **kwargs):
        if kwargs.get("batch_names"):
            await bulk._call(bulk_manager.update_folder, run["bulk_run_id"], "folder", batch_name="other")
        return await original(*args, **kwargs)
    monkeypatch.setattr(bulk_manager, "mutate_async", changed)
    with pytest.raises(BulkRevisionConflict):
        asyncio.run(bulk._process_folder(run["bulk_run_id"], 0))
    assert not batch_manager.is_run_active(path.name)
    job.assert_not_called()


@pytest.mark.parametrize("stop", ["pause", "cancel"])
def test_stop_while_reservation_waits_prevents_ocr(run, monkeypatch, stop):
    from app.api.api_v1.endpoints import batches
    from app.services.ws_manager import ws_manager
    path, _ = associated(run)
    (path / "checkpoint.json").unlink()
    rid = run["bulk_run_id"]
    entered, release = threading.Event(), threading.Event()
    contended = contention(monkeypatch)
    job = AsyncMock()
    monkeypatch.setattr(batches, "run_ocr_task", job)
    def hold():
        entered.set()
        assert release.wait(5)
    async def scenario():
        with ThreadPoolExecutor(1) as pool:
            holder = pool.submit(batch_manager.run_batch_sync, path, hold)
            assert await asyncio.to_thread(entered.wait, 3)
            task = asyncio.create_task(bulk._process_folder(rid, 0))
            try:
                assert await asyncio.to_thread(contended.wait, 3)
                assert await bulk.request_stop_async(rid, pause=stop == "pause")
            finally:
                release.set()
            await task
            holder.result(5)
    asyncio.run(scenario())
    value = bulk_manager.get_run(rid)
    assert value[stop + "_requested"]
    assert value["folders"][0]["status"] == "pending"
    assert not value["checkpoint_error"] and not batch_manager.is_run_active(path.name)
    assert path.name not in ws_manager.cancel_events
    assert not (path / "checkpoint.json").exists()
    job.assert_not_called()


def test_reservation_timeout_keeps_checkpointless_batch_valid(run, monkeypatch):
    from app.api.api_v1.endpoints import batches
    path, _ = associated(run)
    (path / "checkpoint.json").unlink()
    bulk_manager.update_folder(run["bulk_run_id"], "folder", status="pending")
    entered, release = threading.Event(), threading.Event()
    coordinator = batch_manager._registry_coordinator()
    coordinator.timeout = 0
    monkeypatch.setattr(batch_manager, "_registry_coordinator", lambda: coordinator)
    job = AsyncMock()
    monkeypatch.setattr(batches, "run_ocr_task", job)
    async def folders(rid):
        await bulk._process_folder(rid, 0)
    monkeypatch.setattr(bulk, "_drive_folders", folders)
    def hold():
        entered.set()
        assert release.wait(5)
    async def scenario():
        with ThreadPoolExecutor(1) as pool:
            holder = pool.submit(batch_manager.run_batch_sync, path, hold)
            assert await asyncio.to_thread(entered.wait, 3)
            try:
                await asyncio.wait_for(bulk._drive(run["bulk_run_id"]), 3)
            finally:
                release.set()
            holder.result(5)
    asyncio.run(scenario())
    value = bulk_manager.get_run(run["bulk_run_id"])
    assert value["status"] == "paused" and value["error_code"] == "transaction_timeout"
    assert value["folders"][0]["status"] == "pending"
    assert not value["checkpoint_error"] and not bulk_manager.is_any_run_active()
    assert not (path / "checkpoint.json").exists()
    job.assert_not_called()


def test_stop_uuid_alias_reaches_admitted_cancel_event(run):
    event = threading.Event()
    bulk._cancel_targets[run["bulk_run_id"]] = ("associated", event)
    assert bulk.request_pause(run["bulk_run_id"].upper())
    assert event.is_set()


@pytest.mark.parametrize("stop", ["pause_requested", "cancel_requested"])
def test_corrupt_checkpoint_outweighs_stop(run, stop):
    path, _ = associated(run)
    (path / "checkpoint.json").write_text('{"broken":')
    bulk_manager.update_run(run["bulk_run_id"], **{stop: True})
    bulk._finalise(run["bulk_run_id"], "completed")
    value = bulk_manager.get_run(run["bulk_run_id"])
    assert value["status"] == "failed" and value[stop]
    assert value["checkpoint_error"] and value["folders"][0]["integrity_error"]


@pytest.mark.parametrize("stop", ["pause", "cancel"])
def test_stop_after_admitted_reservation_before_ocr_handoff(run, monkeypatch, stop):
    from app.api.api_v1.endpoints import batches
    from app.services.ws_manager import ws_manager
    path, _ = associated(run)
    rid = run["bulk_run_id"]
    original = bulk_manager.mutate_async
    job = AsyncMock()
    monkeypatch.setattr(batches, "run_ocr_task", job)
    async def reserve_then_stop(*args, **kwargs):
        value = await original(*args, **kwargs)
        if kwargs.get("batch_names"):
            assert batch_manager.is_run_active(path.name)
            assert await bulk.request_stop_async(rid, pause=stop == "pause")
        return value
    monkeypatch.setattr(bulk_manager, "mutate_async", reserve_then_stop)
    asyncio.run(bulk._process_folder(rid, 0))
    assert not batch_manager.is_run_active(path.name)
    assert path.name not in ws_manager.cancel_events
    assert bulk_manager.get_run(rid)["folders"][0]["status"] == "pending"
    job.assert_not_called()


def test_existing_batch_reservation_is_never_released_or_restarted(run, monkeypatch):
    from app.api.api_v1.endpoints import batches
    path, _ = associated(run)
    assert batch_manager.acquire_batch_lock(path.name)
    job = AsyncMock()
    monkeypatch.setattr(batches, "run_ocr_task", job)
    try:
        with pytest.raises(bulk.ReservationBusy):
            asyncio.run(bulk._process_folder(run["bulk_run_id"], 0))
        assert batch_manager.is_run_active(path.name)
        assert bulk_manager.get_run(run["bulk_run_id"])["folders"][0]["status"] == "pending"
        job.assert_not_called()
    finally:
        batch_manager.release_batch_lock(path.name)


def test_timeout_integrity_snapshot_never_replaces_counts(run):
    path, _ = associated(run)
    rid = run["bulk_run_id"]
    bulk_manager.update_folder(rid, "folder", status="pending", images_processed=7, images_failed=2)
    write_checkpoint(path / "checkpoint.json", [{"filename": "one.jpg", "success": True}], [])
    bulk._finalise(rid, "paused", checkpoint_gate=False)
    value = bulk_manager.get_run(rid)
    assert value["status"] == "paused" and not value["checkpoint_error"]
    assert value["images_processed"] == 7 and value["images_failed"] == 2


@pytest.mark.parametrize("fault", ["read", "state", "unexpected", "cancel", "seed", "call"])
def test_handoff_failure_releases_only_owned_reservation(run, monkeypatch, caplog, fault):
    from app.api.api_v1.endpoints import batches
    from app.services.bulk_manager import BulkReadError
    from app.services.ws_manager import ws_manager
    path, _ = associated(run)
    rid = run["bulk_run_id"]
    original_mutate = bulk_manager.mutate_async
    original_read = bulk_manager.get_run
    original_release = batch_manager.release_batch_lock
    armed = False
    releases = []
    def release(name):
        releases.append(name)
        original_release(name)
    monkeypatch.setattr(batch_manager, "release_batch_lock", release)
    async def reserve(*args, **kwargs):
        nonlocal armed
        value = await original_mutate(*args, **kwargs)
        if kwargs.get("batch_names"):
            assert batch_manager.is_run_active(path.name)
            armed = True
            if fault == "cancel":
                asyncio.current_task().cancel()
        return value
    def read(*args, **kwargs):
        nonlocal armed
        if armed and fault in {"read", "state", "unexpected"}:
            armed = False
            if fault == "read":
                raise BulkReadError()
            if fault == "state":
                raise BulkStateError()
            raise RuntimeError(SECRET)
        return original_read(*args, **kwargs)
    monkeypatch.setattr(bulk_manager, "mutate_async", reserve)
    monkeypatch.setattr(bulk_manager, "get_run", read)
    job = AsyncMock()
    if fault == "seed":
        original_counts = bulk._folder_counts_from_checkpoint
        def seed_failure(*args, **kwargs):
            if not kwargs:
                raise BulkStateError()
            return original_counts(*args, **kwargs)
        monkeypatch.setattr(bulk, "_folder_counts_from_checkpoint", seed_failure)
    if fault == "call":
        # Fail at coroutine construction, before the OCR lifecycle can accept
        # ownership. This is distinct from an exception inside OCR's try.
        job = Mock(side_effect=RuntimeError(SECRET))
    monkeypatch.setattr(batches, "run_ocr_task", job)
    async def folders(_):
        await bulk._process_folder(rid, 0)
    monkeypatch.setattr(bulk, "_drive_folders", folders)
    assert bulk_manager.acquire_run_lock(rid)
    if fault == "cancel":
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(bulk._drive(rid))
    else:
        asyncio.run(bulk._drive(rid))
    assert releases == [path.name]
    assert not batch_manager.is_run_active(path.name)
    assert not bulk_manager.is_any_run_active()
    assert rid not in bulk._cancel_targets and path.name not in ws_manager.cancel_events
    assert not bulk._tasks
    if fault == "call":
        job.assert_called_once()
    else:
        job.assert_not_called()
    assert_safe(caplog)


@pytest.mark.parametrize("outcome", ["success", "failure", "cancel", "entry_failure"])
def test_real_ocr_accepts_handoff_and_alone_releases_batch(run, monkeypatch, tmp_path, outcome):
    from app.api.api_v1.endpoints import batches
    from app.core.config import settings
    from app.services.ocr_engine import ocr_engine
    from app.services.ws_manager import ws_manager
    path, _ = associated(run)
    rid = run["bulk_run_id"]
    monkeypatch.setattr(settings, "BATCHES_HISTORY_FILE", str(tmp_path / "history.json"))
    batch_manager._record_history(path.name, "Associated")
    (path / "config.json").write_text('{"fields":["field"]}')
    monkeypatch.setattr(batches, "_resolve_provider", lambda *_: ("unused", "mock", None))
    process_calls = []
    if outcome == "entry_failure":
        original_event = ws_manager.get_or_create_cancel_event
        event_calls = 0
        def event(name):
            nonlocal event_calls
            event_calls += 1
            if event_calls == 2:
                raise RuntimeError(SECRET)
            return original_event(name)
        monkeypatch.setattr(ws_manager, "get_or_create_cancel_event", event)
    releases = []
    original_release = batch_manager.release_batch_lock
    def release(name):
        releases.append(name)
        original_release(name)
    monkeypatch.setattr(batch_manager, "release_batch_lock", release)
    async def process(**kwargs):
        process_calls.append(path.name)
        assert batch_manager.is_run_active(path.name)
        assert bulk_manager.is_any_run_active()
        if outcome == "failure":
            raise RuntimeError(SECRET)
        if outcome == "cancel":
            raise asyncio.CancelledError()
        write_checkpoint(path / "checkpoint.json", [{"filename":"done.jpg", "success":True}], [])
    monkeypatch.setattr(ocr_engine, "process_batch", process)
    async def folders(_):
        await bulk._process_folder(rid, 0)
    monkeypatch.setattr(bulk, "_drive_folders", folders)
    assert bulk_manager.acquire_run_lock(rid)
    if outcome == "cancel":
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(bulk._drive(rid))
    else:
        asyncio.run(bulk._drive(rid))
    assert releases == [path.name]
    assert not batch_manager.is_run_active(path.name) and not bulk_manager.is_any_run_active()
    assert rid not in bulk._cancel_targets and path.name not in ws_manager.cancel_events
    assert bool(process_calls) is (outcome != "entry_failure")


@pytest.mark.parametrize("callback_error", [False, True])
@pytest.mark.parametrize("cancel_point", ["entry", "registration"])
def test_cancel_at_drain_entry_joins_callback_before_global_unlock(run, monkeypatch, tmp_path, caplog, callback_error, cancel_point):
    from app.api.api_v1.endpoints import batches
    from app.core.config import settings
    from app.models.schemas import BatchProgress
    from app.services.ocr_engine import ocr_engine
    path, _ = associated(run)
    rid = run["bulk_run_id"]
    monkeypatch.setattr(settings, "BATCHES_HISTORY_FILE", str(tmp_path / "history.json"))
    batch_manager._record_history(path.name, "Associated")
    (path / "config.json").write_text('{"fields":["field"]}')
    monkeypatch.setattr(batches, "_resolve_provider", lambda *_: ("unused", "mock", None))
    entered, release = threading.Event(), threading.Event()
    drain_entered = asyncio.Event()
    callbacks, unobserved, unlocks = [], [], []
    persist = bulk_manager._persist_run
    def hold_progress(current):
        if current["folders"][0]["images_processed"] == 1:
            entered.set()
            assert release.wait(5)
        result = persist(current)
        if callback_error and current["images_processed"] == 1:
            raise RuntimeError(SECRET)
        return result
    monkeypatch.setattr(bulk_manager, "_persist_run", hold_progress)
    async def process(**kwargs):
        write_checkpoint(path / "checkpoint.json", [{"filename":"done.jpg", "success":True}], [])
        callbacks.append(asyncio.create_task(kwargs["progress_callback"](path.name,
            BatchProgress(batch_name=path.name, current=1, total=1, percentage=100, status="running"))))
        assert await asyncio.to_thread(entered.wait, 3)
    monkeypatch.setattr(ocr_engine, "process_batch", process)
    original_drain = bulk._drain_progress
    original_gather = asyncio.gather
    registered = []
    def gather(*tasks, **kwargs):
        if any(task in callbacks for task in tasks):
            registered.append(True)
            if cancel_point == "registration":
                asyncio.current_task().cancel()
        return original_gather(*tasks, **kwargs)
    monkeypatch.setattr(asyncio, "gather", gather)
    async def drain(tasks):
        drain_entered.set()
        # The callback owns a real admitted Bulk commit. Cancel the driver at
        # precisely the first scheduling await inside the production drain.
        if cancel_point == "entry":
            asyncio.get_running_loop().call_soon(asyncio.current_task().cancel)
        await original_drain(tasks)
    monkeypatch.setattr(bulk, "_drain_progress", drain)
    original_unlock = bulk_manager.release_run_lock
    def unlock(expected_id=None):
        assert callbacks and all(task.done() for task in callbacks)
        assert bulk_manager.get_run(rid)["images_processed"] == 1
        unlocks.append(expected_id)
        original_unlock(expected_id)
    monkeypatch.setattr(bulk_manager, "release_run_lock", unlock)
    async def folders(_):
        await bulk._process_folder(rid, 0)
    monkeypatch.setattr(bulk, "_drive_folders", folders)
    async def scenario():
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(lambda _, context: unobserved.append(context))
        assert bulk_manager.acquire_run_lock(rid)
        driver = asyncio.create_task(bulk._drive(rid))
        bulk._tasks[rid] = driver
        try:
            await asyncio.wait_for(drain_entered.wait(), 3)
            assert not batch_manager.is_run_active(path.name)
            assert bulk_manager.is_any_run_active()
            for _ in range(3):
                driver.cancel()
                await asyncio.sleep(0)
                assert not driver.done() and not callbacks[0].done()
                assert bulk_manager.is_any_run_active() and not unlocks
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await driver
        assert callbacks[0].done() and callbacks[0].exception() is None
        await asyncio.sleep(0)
    asyncio.run(scenario())
    assert registered == [True]
    assert unlocks == [rid] and not bulk_manager.is_any_run_active()
    assert not unobserved and not bulk._tasks and not bulk._cancel_targets
    assert_safe(caplog)
    if callback_error:
        assert "bulk_progress_failed" in caplog.text


@pytest.mark.parametrize("stop", ["none", "pause", "cancel", "integrity", "terminal"])
def test_start_cancellation_compensation_uses_latest_stop(monkeypatch, stop):
    value = make_run()
    rid = value["bulk_run_id"]
    entered, release = threading.Event(), threading.Event()
    undo_entered, allow_undo = asyncio.Event(), asyncio.Event()
    persist = bulk_manager._persist_run
    held = False
    def hold_commit(current):
        nonlocal held
        if current["status"] == "running" and not held:
            held = True
            entered.set()
            assert release.wait(5)
        return persist(current)
    monkeypatch.setattr(bulk_manager, "_persist_run", hold_commit)
    original_call = bulk._call
    async def call(operation, *args, **kwargs):
        if getattr(operation, "__name__", "") == "undo":
            undo_entered.set()
            await allow_undo.wait()
        return await original_call(operation, *args, **kwargs)
    monkeypatch.setattr(bulk, "_call", call)
    planned = AsyncMock()
    monkeypatch.setattr(bulk, "_drive", planned)
    async def scenario():
        task = asyncio.create_task(bulk.start_run(rid))
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            task.cancel()
        finally:
            release.set()
        await asyncio.wait_for(undo_entered.wait(), 3)
        assert bulk_manager.get_run(rid)["status"] == "running"
        if stop in {"pause", "cancel", "integrity"}:
            assert await bulk.request_stop_async(rid, pause=stop == "pause")
        if stop == "integrity":
            await original_call(bulk_manager.update_folder, rid, "folder", integrity_error="checkpoint_invalid")
        elif stop == "terminal":
            await original_call(bulk_manager.update_run, rid, status="completed")
            assert not await bulk.request_stop_async(rid, pause=False)
        allow_undo.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        expected = {"none":"interrupted", "pause":"paused", "cancel":"cancelled", "integrity":"failed", "terminal":"completed"}[stop]
        current = bulk_manager.get_run(rid)
        assert current["status"] == expected
        assert bool(current["pause_requested"]) is (stop == "pause")
        assert bool(current["cancel_requested"]) is (stop in {"cancel", "integrity"})
        assert not bulk_manager.is_any_run_active() and not bulk._tasks
        planned.assert_not_called()
        if stop in {"cancel", "integrity"}:
            results = await asyncio.gather(bulk.start_run(rid), bulk.start_run(rid), return_exceptions=True)
            assert all(isinstance(item, (RuntimeError, CheckpointError)) for item in results)
            assert bulk_manager.get_run(rid)["cancel_requested"]
            planned.assert_not_called()
        if stop == "integrity":
            assert current["folders"][0]["integrity_error"] == "checkpoint_invalid"
    asyncio.run(scenario())


@pytest.mark.parametrize("status", ["interrupted", "paused", "queued"])
def test_resume_rejects_preexisting_cancel_latch_without_planning(monkeypatch, status):
    value = make_run()
    rid = value["bulk_run_id"]
    bulk_manager.update_run(rid, status=status, cancel_requested=True)
    before = bulk_manager._run_json(rid).read_bytes()
    planned = AsyncMock()
    monkeypatch.setattr(bulk, "_drive", planned)
    async def scenario():
        results = await asyncio.gather(bulk.start_run(rid), bulk.start_run(rid), return_exceptions=True)
        assert all(isinstance(item, RuntimeError) for item in results)
    asyncio.run(scenario())
    planned.assert_not_called()
    assert bulk_manager._run_json(rid).read_bytes() == before
    assert not bulk_manager.is_any_run_active() and not bulk._tasks
