"""SAR-04b: real gates, deterministic mutator interleavings, no provider network."""
import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import BackgroundTasks, HTTPException

from app.api.api_v1.endpoints import batches
from app.core.checkpoint import CheckpointWriteError, read_checkpoint, write_checkpoint
from app.models.schemas import ResultPatch
from app.services.batch_manager import batch_manager
from app.services.ocr_engine import ocr_engine
from app.services.validation import runner
from test_error_disclosure import SECRET, assert_safe
from test_error_disclosure import isolated_state as isolated_state


def row(name="old.jpg"):
    return {"filename": name, "success": True, "duration": 0, "data": {"value": "old"}}


@pytest.fixture
def batch():
    path = batch_manager.batches_dir / "coordinated"
    path.mkdir()
    (path / "config.json").write_text(json.dumps({"provider": "ollama", "field_rules": {"value": {"pattern": ".*"}}}))
    write_checkpoint(path / "checkpoint.json", [row()], [{"id": "original"}])
    return path


def wait(event):
    assert event.wait(5), "Synchronization failed"


@pytest.mark.parametrize("endpoint", ["patch", "revalidate"])
@pytest.mark.parametrize("blocker", ["run", "recovery"])
def test_curator_conflicts_preserve_checkpoint(client, batch, caplog, endpoint, blocker):
    if blocker == "run":
        assert batch_manager.acquire_batch_lock(batch.name)
    else:
        (batch / ".retry-recovery.json").write_text('{}')
    alias = alias_for(batch)
    original = (batch / "checkpoint.json").read_bytes()
    response = client.patch(f"/api/v1/batches/{alias.name}/results/old.jpg", json={"field":"value", "value":"new", "audit_entry":{"id":"rejected"}}) if endpoint == "patch" else client.post(f"/api/v1/batches/{alias.name}/revalidate")
    assert response.status_code == 409
    assert (batch / "checkpoint.json").read_bytes() == original
    assert_safe(caplog, response.text)


@pytest.mark.parametrize("alias", [False, True])
def test_concurrent_patches_keep_both_fields_and_audits(batch, monkeypatch, alias):
    entered, release, contended = threading.Event(), threading.Event(), threading.Event()
    original_read = batches.read_checkpoint
    first = True

    def read(path):
        nonlocal first
        result = original_read(path)
        if first:
            first = False
            entered.set()
            wait(release)
        return result

    from app.core import transactions
    real_flock = transactions.fcntl.flock

    def flock(fd, flags):
        try:
            return real_flock(fd, flags)
        except BlockingIOError:
            contended.set()
            raise

    monkeypatch.setattr(batches, "read_checkpoint", read)
    monkeypatch.setattr(transactions.fcntl, "flock", flock)

    other = batch.name
    if alias:
        other = batch.name.upper()
        alias_path = batch.with_name(other)
        if not alias_path.exists():
            alias_path.symlink_to(batch, target_is_directory=True)
        assert alias_path.samefile(batch)

    def patch(field):
        return asyncio.run(batches.patch_result(other if field == "b" else batch.name, "old.jpg", ResultPatch(field=field, value=field, audit_entry={"id":field})))

    with ThreadPoolExecutor(2) as pool:
        a = pool.submit(patch, "a")
        wait(entered)
        b = pool.submit(patch, "b")
        try:
            wait(contended)
            assert not b.done()
        finally:
            release.set()
        assert a.result(5) == b.result(5) == {"ok": True}
    rows, audit = read_checkpoint(batch / "checkpoint.json")
    assert rows[0]["edited_data"] == {"a":"a", "b":"b"}
    assert audit == [{"id":"original"}, {"id":"a"}, {"id":"b"}]


@pytest.mark.parametrize("change", ["patch", "config", "retry", "start", "full_start"])
def test_revalidation_detects_intervening_change_without_losing_audit(batch, monkeypatch, change):
    entered, release = threading.Event(), threading.Event()

    def validate(**kwargs):
        entered.set()
        wait(release)
        return {"value": {"status":"valid"}}

    monkeypatch.setattr(runner, "run_validation", validate)
    if change != "full_start":
        monkeypatch.setattr(batches, "run_ocr_task", AsyncMock())
    monkeypatch.setattr(batches, "_resolve_provider", lambda *_: ("unused", "mock", None))

    async def scenario():
        task = asyncio.create_task(batches.revalidate_batch(batch.name))
        assert await asyncio.to_thread(entered.wait, 3)
        try:
            if change == "patch":
                await batches.patch_result(alias_for(batch).name, "old.jpg", ResultPatch(field="value", value="curated", audit_entry={"id":"curated"}))
            elif change == "config":
                await batch_manager.run_batch_async(batch, lambda: (batch / "config.json").write_text('{"field_rules":{},"provider":"ollama"}'))
            elif change == "retry":
                (batch / "_errors").mkdir()
                (batch / "_errors" / "bad.jpg").write_bytes(b"image")
                write_checkpoint(batch / "checkpoint.json", [row(), {"filename":"bad.jpg", "success":False}], [{"id":"original"}])
                await batches.retry_image(batch.name, "bad.jpg", BackgroundTasks())
            elif change == "full_start":
                from starlette.requests import Request
                from app.models.schemas import BatchStartRequest
                (batch / "new.jpg").write_bytes(b"image")
                monkeypatch.setattr(ocr_engine, "_process_card_sync", lambda *a, **k: row("new.jpg"))
                background = BackgroundTasks()
                request = Request({"type":"http", "method":"POST", "path":"/test", "headers":[], "client":("127.0.0.1",1), "state":{}})
                await batches.start_batch(request, batch.name, background, BatchStartRequest(provider="ollama"))
                await background()
                assert not batch_manager.is_run_active(batch.name)
                assert {r["filename"] for r in read_checkpoint(batch / "checkpoint.json")[0]} == {"old.jpg", "new.jpg"}
            else:
                await batch_manager.reserve_batch_async(batch.name)
            expected = (batch / "checkpoint.json").read_bytes()
        finally:
            release.set()
        with pytest.raises(HTTPException) as error:
            await task
        assert error.value.status_code == 409
        assert (batch / "checkpoint.json").read_bytes() == expected
    asyncio.run(scenario())
    rows, audit = read_checkpoint(batch / "checkpoint.json")
    assert "validation" not in rows[0]
    assert audit == ([{"id":"original"}, {"id":"curated"}] if change == "patch" else [{"id":"original"}])


@pytest.mark.parametrize("endpoint", ["patch", "revalidate"])
def test_real_ocr_provider_inflight_rejects_curator_changes(batch, monkeypatch, endpoint):
    entered, release = threading.Event(), threading.Event()
    (batch / "new.jpg").write_bytes(b"image")

    def provider(*args, **kwargs):
        entered.set()
        wait(release)
        return {"fields":{"value":"new"}}, None

    monkeypatch.setattr(ocr_engine, "_call_vlm_api_resilient", provider)
    monkeypatch.setattr(batches, "_resolve_provider", lambda *_: ("unused", "mock", None))
    assert batch_manager.acquire_batch_lock(batch.name)

    async def scenario():
        task = asyncio.create_task(batches.run_ocr_task(batch.name))
        assert await asyncio.to_thread(entered.wait, 3)
        try:
            with pytest.raises(HTTPException) as error:
                if endpoint == "patch":
                    await batches.patch_result(alias_for(batch).name, "old.jpg", ResultPatch(field="value", value="bad", audit_entry={"id":"rejected"}))
                else:
                    await batches.revalidate_batch(batch.name)
            assert error.value.status_code == 409
        finally:
            release.set()
        await task
    asyncio.run(scenario())
    rows, audit = read_checkpoint(batch / "checkpoint.json")
    assert {r["filename"] for r in rows} == {"old.jpg", "new.jpg"}
    assert "edited_data" not in rows[0] and audit == [{"id":"original"}]
    assert not batch_manager.is_run_active(batch.name)


def test_direct_engine_revision_guard_preserves_concurrent_curator_write(batch, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    (batch / "new.jpg").write_bytes(b"image")

    def provider(*args, **kwargs):
        entered.set()
        wait(release)
        return {"fields":{"value":"new"}}, None
    monkeypatch.setattr(ocr_engine, "_call_vlm_api_resilient", provider)

    async def scenario():
        task = asyncio.create_task(ocr_engine.process_batch(batch))
        assert await asyncio.to_thread(entered.wait, 3)
        try:
            await batches.patch_result(batch.name, "old.jpg", ResultPatch(field="value", value="kept", audit_entry={"id":"kept"}))
            expected = (batch / "checkpoint.json").read_bytes()
        finally:
            release.set()
        with pytest.raises(CheckpointWriteError):
            await task
        assert (batch / "checkpoint.json").read_bytes() == expected
    asyncio.run(scenario())
    assert read_checkpoint(batch / "checkpoint.json")[1] == [{"id":"original"}, {"id":"kept"}]


@pytest.mark.parametrize("endpoint", ["patch", "revalidate"])
def test_administrative_recovery_and_patch_share_gate(batch, monkeypatch, endpoint):
    (batch / "_errors").mkdir()
    (batch / "_errors" / "bad.jpg").write_bytes(b"image")
    batch_manager.begin_retry_preparation(batch.name, [batch / "_errors" / "bad.jpg"])
    entered, release, contended = threading.Event(), threading.Event(), threading.Event()
    real_recover = batch_manager._recover_retry

    def recover(*args, **kwargs):
        entered.set()
        wait(release)
        return real_recover(*args, **kwargs)

    from app.core import transactions
    real_flock = transactions.fcntl.flock

    def flock(fd, flags):
        try:
            return real_flock(fd, flags)
        except BlockingIOError:
            contended.set()
            raise
    monkeypatch.setattr(batch_manager, "_recover_retry", recover)
    monkeypatch.setattr(transactions.fcntl, "flock", flock)
    with ThreadPoolExecutor(2) as pool:
        recovery = pool.submit(batch_manager.recover_retry, batch.name)
        wait(entered)
        operation = batches.patch_result(batch.name, "old.jpg", ResultPatch(field="value", value="after", audit_entry={"id":"after"})) if endpoint == "patch" else batches.revalidate_batch(batch.name)
        patch = pool.submit(asyncio.run, operation)
        try:
            wait(contended)
            assert not patch.done() and batch_manager.retry_recovery_required(batch.name)
        finally:
            release.set()
        recovery.result(5)
        result = patch.result(5)
        assert result == {"ok":True} if endpoint == "patch" else result["validated_count"] == 1
    assert read_checkpoint(batch / "checkpoint.json")[1] == ([{"id":"original"}, {"id":"after"}] if endpoint == "patch" else [{"id":"original"}])


@pytest.mark.parametrize("retry_all", [False, True])
@pytest.mark.parametrize("endpoint", ["patch", "revalidate"])
def test_retry_preparation_serializes_against_patch(batch, monkeypatch, retry_all, endpoint):
    (batch / "_errors").mkdir()
    (batch / "_errors" / "bad.jpg").write_bytes(b"image")
    entered, release, contended = threading.Event(), threading.Event(), threading.Event()
    real_prepare = batches._prepare_retry_images

    def prepare(*args, **kwargs):
        entered.set()
        wait(release)
        return real_prepare(*args, **kwargs)

    from app.core import transactions
    real_flock = transactions.fcntl.flock

    def flock(fd, flags):
        try:
            return real_flock(fd, flags)
        except BlockingIOError:
            contended.set()
            raise
    monkeypatch.setattr(batches, "_prepare_retry_images", prepare)
    monkeypatch.setattr(transactions.fcntl, "flock", flock)

    def retry():
        return asyncio.run(batches.retry_batch(batch.name, BackgroundTasks()) if retry_all else batches.retry_image(batch.name, "bad.jpg", BackgroundTasks()))

    with ThreadPoolExecutor(2) as pool:
        job = pool.submit(retry)
        wait(entered)
        operation = batches.patch_result(batch.name, "old.jpg", ResultPatch(field="value", value="rejected", audit_entry={"id":"rejected"})) if endpoint == "patch" else batches.revalidate_batch(batch.name)
        patch = pool.submit(asyncio.run, operation)
        try:
            wait(contended)
            assert not patch.done()
        finally:
            release.set()
        job.result(5)
        with pytest.raises(HTTPException) as error:
            patch.result(5)
        assert error.value.status_code == 409
    assert read_checkpoint(batch / "checkpoint.json")[1] == [{"id":"original"}]


def test_cancel_during_writer_commit_joins_before_unlock(batch, monkeypatch, caplog):
    entered, release, exited = threading.Event(), threading.Event(), threading.Event()
    (batch / "new.jpg").write_bytes(b"image")
    monkeypatch.setattr(batches, "_resolve_provider", lambda *_: ("unused", "mock", None))
    monkeypatch.setattr(ocr_engine, "_call_vlm_api_resilient", lambda *a, **k: ({"fields":{"value":"new"}}, None))
    from app.services import ocr_engine as module
    real_write = module.write_checkpoint

    def write(*args):
        entered.set()
        wait(release)
        try:
            return real_write(*args)
        finally:
            exited.set()
    monkeypatch.setattr(module, "write_checkpoint", write)
    assert batch_manager.acquire_batch_lock(batch.name)

    async def scenario():
        task = asyncio.create_task(batches.run_ocr_task(batch.name))
        assert await asyncio.to_thread(entered.wait, 3)
        for _ in range(3):
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done() and batch_manager.is_run_active(batch.name)
        with pytest.raises(RuntimeError):
            await asyncio.to_thread(batch_manager.delete_batch, batch.name)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert exited.is_set() and not batch_manager.is_run_active(batch.name)
    try:
        asyncio.run(scenario())
    finally:
        release.set()
    assert read_checkpoint(batch / "checkpoint.json")[1] == [{"id":"original"}]
    assert_safe(caplog)


def test_cancelled_retry_preparation_does_not_schedule_or_leak_lock(batch, monkeypatch):
    write_checkpoint(batch / "checkpoint.json", [row(), {"filename":"bad.jpg", "success":False}], [{"id":"original"}])
    (batch / "_errors").mkdir()
    (batch / "_errors" / "bad.jpg").write_bytes(b"image")
    entered, release = threading.Event(), threading.Event()
    real_prepare = batches._prepare_retry_images

    def prepare(*args, **kwargs):
        entered.set()
        wait(release)
        return real_prepare(*args, **kwargs)
    monkeypatch.setattr(batches, "_prepare_retry_images", prepare)
    background = BackgroundTasks()

    async def scenario():
        task = asyncio.create_task(batches.retry_image(batch.name, "bad.jpg", background))
        assert await asyncio.to_thread(entered.wait, 3)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done() and batch_manager.is_run_active(batch.name)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not background.tasks and not batch_manager.is_run_active(batch.name)
    try:
        asyncio.run(scenario())
    finally:
        release.set()
    assert (batch / "bad.jpg").read_bytes() == b"image"
    rows, audit = read_checkpoint(batch / "checkpoint.json")
    assert [item["filename"] for item in rows] == ["old.jpg"]
    assert audit == [{"id":"original"}]


def test_successful_revalidation_keeps_edits_and_audit(client, batch):
    assert client.patch(f"/api/v1/batches/{batch.name}/results/old.jpg", json={"field":"value", "value":"curated", "audit_entry":{"id":"kept"}}).status_code == 200
    response = client.post(f"/api/v1/batches/{batch.name}/revalidate")
    assert response.status_code == 200 and response.json()["validated_count"] == 1
    rows, audit = read_checkpoint(batch / "checkpoint.json")
    assert rows[0]["edited_data"] == {"value":"curated"}
    assert rows[0]["validation"]["value"]["status"] == "valid"
    assert audit == [{"id":"original"}, {"id":"kept"}]


@pytest.mark.parametrize("fault", ["patch_read", "patch_write", "revalidation_compute", "revalidation_write"])
def test_new_failures_do_not_disclose_sentinel(client, batch, monkeypatch, caplog, fault):
    before = (batch / "checkpoint.json").read_bytes()
    failure = Mock(side_effect=RuntimeError(SECRET))
    if fault == "patch_read":
        monkeypatch.setattr(batches, "read_checkpoint", failure)
    elif fault in {"patch_write", "revalidation_write"}:
        monkeypatch.setattr(batches, "write_checkpoint", failure)
    else:
        monkeypatch.setattr(runner, "run_validation", failure)
    response = client.patch(f"/api/v1/batches/{batch.name}/results/old.jpg", json={"field":"value", "value":"new"}) if fault.startswith("patch") else client.post(f"/api/v1/batches/{batch.name}/revalidate")
    assert response.status_code == 500
    failure.assert_called_once()
    assert (batch / "checkpoint.json").read_bytes() == before
    assert_safe(caplog, response.text)


@pytest.mark.parametrize("fail", [False, True])
def test_revalidation_cancel_joins_unlocked_calculation_without_commit(batch, monkeypatch, caplog, fail):
    entered, release, exited = threading.Event(), threading.Event(), threading.Event()

    def validate(**kwargs):
        entered.set()
        wait(release)
        exited.set()
        if fail:
            raise RuntimeError(SECRET)
        return {"value":{"status":"valid"}}
    monkeypatch.setattr(runner, "run_validation", validate)

    async def scenario():
        task = asyncio.create_task(batches.revalidate_batch(batch.name))
        assert await asyncio.to_thread(entered.wait, 3)
        for _ in range(3):
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
        # Calculation cannot hold the batch gate, even while cancelled/joining.
        await batches.patch_result(batch.name, "old.jpg", ResultPatch(field="value", value="kept", audit_entry={"id":"kept"}))
        expected = (batch / "checkpoint.json").read_bytes()
        release.set()
        with pytest.raises(RuntimeError if fail else asyncio.CancelledError):
            await task
        assert exited.is_set() and (batch / "checkpoint.json").read_bytes() == expected
    try:
        asyncio.run(scenario())
    finally:
        release.set()
    assert_safe(caplog)


def test_cancelled_start_preparation_releases_only_unscheduled_reservation(batch, monkeypatch):
    from starlette.requests import Request
    from app.models.schemas import BatchStartRequest
    entered, release = threading.Event(), threading.Event()
    original = batches._start_preparation
    monkeypatch.setattr(batches, "_resolve_provider", lambda *_: ("unused", "mock", None))

    def prepare(*args):
        value = original(*args)
        entered.set()
        wait(release)
        return value
    monkeypatch.setattr(batches, "_start_preparation", prepare)
    background = BackgroundTasks()
    request = Request({"type":"http", "method":"POST", "path":"/test", "headers":[], "client":("127.0.0.1",1), "state":{}})

    async def scenario():
        task = asyncio.create_task(batches.start_batch(request, batch.name, background, BatchStartRequest(provider="ollama")))
        assert await asyncio.to_thread(entered.wait, 3)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done() and batch_manager.is_run_active(batch.name)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not background.tasks and not batch_manager.is_run_active(batch.name)
    try:
        asyncio.run(scenario())
    finally:
        release.set()


def test_failed_run_reservation_never_schedules_or_leaks_lock(client, batch, monkeypatch, caplog):
    monkeypatch.setattr(batches, "_resolve_provider", lambda *_: ("unused", "mock", None))
    from app.services import batch_manager as module
    failure = Mock(side_effect=OSError(SECRET))
    monkeypatch.setattr(module.os, "write", failure)
    job = AsyncMock()
    monkeypatch.setattr(batches, "run_ocr_task", job)
    before = (batch / "checkpoint.json").read_bytes()
    response = client.post(f"/api/v1/batches/{batch.name}/start", json={"provider":"ollama"})
    assert response.status_code == 500
    failure.assert_called_once()
    job.assert_not_called()
    assert not batch_manager.is_run_active(batch.name)
    assert (batch / "checkpoint.json").read_bytes() == before
    assert_safe(caplog, response.text)


@pytest.mark.parametrize("stop", ["pause", "cancel"])
def test_bulk_stop_during_gated_reservation_starts_no_ocr(batch, monkeypatch, stop):
    from app.services import bulk_orchestrator
    from app.services.bulk_manager import bulk_manager
    from test_error_disclosure import make_run
    run = make_run()
    run["status"] = "running"  # Exercise the active-driver reservation contract.
    run["folders"][0].update(batch_name=batch.name, status="pending")
    bulk_manager.save_run(run)
    entered, release = threading.Event(), threading.Event()
    original = bulk_manager.mutate_async

    async def reserve(*args, **kwargs):
        result = await original(*args, **kwargs)
        if kwargs.get("batch_names"):
            # The compound reservation gate is released; hold its return before
            # the mandatory post-await stop check, with the real run lock held.
            entered.set()
            assert await asyncio.to_thread(release.wait, 5)
        return result
    monkeypatch.setattr(bulk_manager, "mutate_async", reserve)
    ocr = AsyncMock()
    monkeypatch.setattr(batches, "run_ocr_task", ocr)

    async def scenario():
        task = asyncio.create_task(bulk_orchestrator._process_folder(run["bulk_run_id"], 0))
        assert await asyncio.to_thread(entered.wait, 3)
        request = bulk_orchestrator.request_pause if stop == "pause" else bulk_orchestrator.request_cancel
        assert await asyncio.to_thread(request, run["bulk_run_id"])
        release.set()
        await task
    try:
        asyncio.run(scenario())
    finally:
        release.set()
    ocr.assert_not_called()
    assert not batch_manager.is_run_active(batch.name)
    assert bulk_manager.get_run(run["bulk_run_id"])["folders"][0]["status"] == "pending"


def test_post_preparation_failure_releases_unscheduled_run(batch, monkeypatch):
    from app.core.transactions import TransactionIOError
    (batch / "_errors").mkdir()
    (batch / "_errors" / "bad.jpg").write_bytes(b"image")
    original = batch_manager.run_batch_async

    async def failed_cleanup(path, operation):
        await original(path, operation)
        raise TransactionIOError()  # Failure after the preparation callback.
    monkeypatch.setattr(batch_manager, "run_batch_async", failed_cleanup)
    background = BackgroundTasks()
    with pytest.raises(HTTPException) as error:
        asyncio.run(batches.retry_image(batch.name, "bad.jpg", background))
    assert error.value.status_code == 500 and not background.tasks
    assert not batch_manager.is_run_active(batch.name)
    assert (batch / "bad.jpg").read_bytes() == b"image"


def alias_for(batch):
    alias = batch.with_name(batch.name.upper())
    if not alias.exists():
        alias.symlink_to(batch, target_is_directory=True)
    assert alias.samefile(batch)
    return alias


def test_physical_identity_and_recreation(batch):
    canonical = batch_manager._canonical_path(batch)
    assert batch_manager._canonical_path(alias_for(batch)) == canonical
    other = batch.with_name("different")
    other.mkdir()
    assert batch_manager._canonical_path(other) != canonical
    upper = other.with_name("DIFFERENT")
    if not upper.exists():
        upper.mkdir()
        assert batch_manager._canonical_path(upper) != batch_manager._canonical_path(other)
    empty = batch.with_name("recreated")
    empty.mkdir()
    before = batch_manager._canonical_path(empty)
    empty.rmdir()
    empty.mkdir()
    assert batch_manager._canonical_path(empty) == before


@pytest.mark.parametrize("stop", [None, "pause", "cancel"])
@pytest.mark.parametrize("checkpoint", ["missing", "corrupt", "latched"])
def test_real_bulk_reservation_timeout(batch, monkeypatch, caplog, stop, checkpoint):
    from app.core import transactions
    from app.services import bulk_orchestrator as bulk
    from app.services.bulk_manager import bulk_manager
    from test_error_disclosure import make_run
    run = make_run()
    run["status"] = "running"
    folder = run["folders"][0]
    folder.update(batch_name=batch.name, status="pending")
    if checkpoint == "missing":
        (batch / "checkpoint.json").unlink()
    elif checkpoint == "corrupt":
        (batch / "checkpoint.json").write_text('{'+SECRET)
        folder["images_processed"] = 1
    else:
        folder["integrity_error"] = "checkpoint_invalid"
    bulk_manager.save_run(run)
    monkeypatch.setattr(bulk, "_validate_run_preconditions", lambda *_: None)
    ocr = AsyncMock()
    monkeypatch.setattr(batches, "run_ocr_task", ocr)
    entered, release, contended, expire = (threading.Event() for _ in range(4))
    original_transactions = batch_manager._transactions
    def coordinator(path):
        value = original_transactions(path)
        value.timeout = 1
        return value
    monkeypatch.setattr(batch_manager, "_transactions", coordinator)
    real_flock = transactions.fcntl.flock
    def flock(fd, flags):
        try:
            return real_flock(fd, flags)
        except BlockingIOError:
            contended.set()
            wait(expire)
            raise
    monkeypatch.setattr(transactions.fcntl, "flock", flock)
    clock = transactions.time.monotonic
    monkeypatch.setattr(transactions.time, "monotonic", lambda: clock() + (10 if expire.is_set() else 0))
    def hold():
        entered.set()
        wait(release)
    async def scenario():
        with ThreadPoolExecutor(1) as pool:
            holder = pool.submit(batch_manager.run_batch_sync, batch, hold)
            assert await asyncio.to_thread(entered.wait, 3)
            task = asyncio.create_task(bulk._drive(run["bulk_run_id"]))
            try:
                assert await asyncio.to_thread(contended.wait, 3)
                if stop:
                    request = bulk.request_pause if stop == "pause" else bulk.request_cancel
                    accepted = await asyncio.to_thread(request, run["bulk_run_id"])
                    assert accepted is (checkpoint != "latched")
                expire.set()
                await task
            finally:
                expire.set()
                release.set()
            holder.result(5)
    asyncio.run(scenario())
    result = bulk_manager.get_run(run["bulk_run_id"])
    ocr.assert_not_called()
    assert not batch_manager.is_run_active(batch.name)
    if checkpoint == "missing":
        assert not result.get("checkpoint_error")
        assert not result["folders"][0].get("integrity_error")
        assert result["folders"][0]["status"] == "pending"
        assert result["status"] == ("cancelled" if stop == "cancel" else "paused")
        assert result["error_code"] == "transaction_timeout"
    else:
        assert result["checkpoint_error"] and result["status"] == "failed"
        assert result["folders"][0]["integrity_error"] == "checkpoint_invalid"
    if stop:
        assert bool(result[stop+"_requested"]) is (checkpoint != "latched")
    from app.services.bulk_progress import to_progress, bulk_channel
    from app.services.ws_manager import ws_manager
    progress = to_progress(result)
    assert ws_manager.bulk_states[bulk_channel(run["bulk_run_id"])].model_dump() == progress.model_dump()
    assert progress.status == result["status"]
    assert_safe(caplog, result, progress)


def test_checkpoint_fingerprint_describes_parsed_bytes(batch, monkeypatch):
    import hashlib
    from app.core import checkpoint
    before = (batch / "checkpoint.json").read_bytes()
    original = checkpoint._parse_checkpoint
    def parse(data):
        value = original(data)
        (batch / "checkpoint.json").write_text('{"results":[],"audit":[]}')
        return value
    monkeypatch.setattr(checkpoint, "_parse_checkpoint", parse)
    rows, audit, revision = checkpoint.read_checkpoint_snapshot(batch / "checkpoint.json")
    assert rows == [row()] and audit == [{"id":"original"}]
    assert revision == hashlib.sha256(before).digest()
    assert revision != hashlib.sha256((batch / "checkpoint.json").read_bytes()).digest()


def test_revalidation_config_revision_describes_parsed_bytes(batch, monkeypatch):
    import hashlib
    before = (batch / "config.json").read_bytes()
    original = batches.json.loads
    def parse(payload, *args, **kwargs):
        value = original(payload, *args, **kwargs)
        if isinstance(value, dict) and "provider" in value:
            (batch / "config.json").write_text('{"provider":"changed"}')
        return value
    monkeypatch.setattr(batches.json, "loads", parse)
    config, rows, audit, revision = batch_manager.run_batch_sync(batch, lambda: batches._revalidation_snapshot(batch))
    assert config["provider"] == "ollama" and rows == [row()] and audit == [{"id":"original"}]
    assert revision[0] == hashlib.sha256(before).digest()
    assert revision != batches._revalidation_revision(batch)


@pytest.mark.parametrize("stop", ["pause", "cancel"])
def test_bulk_stop_while_waiting_skips_reservation(batch, monkeypatch, stop):
    from app.core import transactions
    from app.services import bulk_orchestrator as bulk
    from app.services.bulk_manager import bulk_manager
    from test_error_disclosure import make_run
    run = make_run()
    run["status"] = "running"  # Exercise the active-driver reservation contract.
    run["folders"][0].update(batch_name=batch.name, status="pending")
    bulk_manager.save_run(run)
    entered, release, contended = threading.Event(), threading.Event(), threading.Event()
    real_flock = transactions.fcntl.flock
    def flock(fd, flags):
        try:
            return real_flock(fd, flags)
        except BlockingIOError:
            contended.set()
            raise
    monkeypatch.setattr(transactions.fcntl, "flock", flock)
    acquire = Mock(wraps=batch_manager.acquire_batch_lock)
    monkeypatch.setattr(batch_manager, "acquire_batch_lock", acquire)
    ocr = AsyncMock()
    monkeypatch.setattr(batches, "run_ocr_task", ocr)
    def hold():
        entered.set()
        wait(release)
    async def scenario():
        with ThreadPoolExecutor(1) as pool:
            holder = pool.submit(batch_manager.run_batch_sync, batch, hold)
            assert await asyncio.to_thread(entered.wait, 3)
            task = asyncio.create_task(bulk._process_folder(run["bulk_run_id"], 0))
            try:
                assert await asyncio.to_thread(contended.wait, 3)
                request = bulk.request_pause if stop == "pause" else bulk.request_cancel
                assert await asyncio.to_thread(request, run["bulk_run_id"])
            finally:
                release.set()
            await task
            holder.result(5)
    asyncio.run(scenario())
    acquire.assert_not_called()
    ocr.assert_not_called()
    result = bulk_manager.get_run(run["bulk_run_id"])
    assert result[stop+"_requested"] and result["folders"][0]["status"] == "pending"


@pytest.mark.parametrize("picked_by", ["manual", "auto"])
def test_reconciliation_round_trip_edit_and_undo(client, batch, picked_by):
    match = {
        "authority": "gnd-persons",
        "uri": "https://d-nb.info/gnd/118540238",
        "label": "Example",
        "picked_by": picked_by,
        "picked_at": "2026-01-01T00:00:00Z",
    }
    url = f"/api/v1/batches/{batch.name}/results"

    def patch(**fields):
        return client.patch(f"{url}/old.jpg", json={"field": "value", "return_result": True, **fields})

    def reloaded_match():
        response = client.get(url)
        assert response.status_code == 200
        return response.json()["results"][0]["validation"]["value"]["reconciliation"]

    saved = patch(reconciliation=match, expected_value="old")
    assert saved.status_code == 200
    assert saved.json()["result"]["validation"]["value"]["reconciliation"] == match
    assert reloaded_match() == match

    assert patch(value="old", validation_status="verified").status_code == 200
    assert client.post(f"/api/v1/batches/{batch.name}/revalidate").status_code == 200
    assert reloaded_match() == match

    assert patch(value="new").status_code == 200
    assert reloaded_match() is None
    assert patch(reconciliation=match, expected_value="old").status_code == 409
    assert reloaded_match() is None

    # Undo writes the old value and its match in the same transaction.
    assert patch(value="old", reconciliation=match, expected_value="new",
                 expected_reconciliation=match).status_code == 409
    assert reloaded_match() is None
    assert patch(value="old", reconciliation=match, expected_value="new",
                 expected_reconciliation=None).status_code == 200
    assert reloaded_match() == match
    assert patch(value="").status_code == 200
    assert reloaded_match() is None
    assert patch(clear_reconciliation=True).status_code == 200
    assert reloaded_match() is None


def test_reconciliation_rejects_page_level_match_for_multiple_entries(client, batch):
    checkpoint = batch / "checkpoint.json"
    multi_entry = row()
    multi_entry["data"] = {"_entries": json.dumps([{"value": "One"}, {"value": "Two"}])}
    write_checkpoint(checkpoint, [multi_entry], [])
    before = checkpoint.read_bytes()
    response = client.patch(
        f"/api/v1/batches/{batch.name}/results/old.jpg",
        json={"field": "value", "reconciliation": {"uri": "https://d-nb.info/gnd/118540238"}},
    )
    assert response.status_code == 400
    assert checkpoint.read_bytes() == before


def test_results_edit_guards_value_and_match_and_preserves_confirmed_row(client, batch):
    url = f"/api/v1/batches/{batch.name}/results/old.jpg"
    match = {"authority": "gnd-persons", "uri": "https://example.invalid/gnd/synthetic"}

    def patch(**fields):
        return client.patch(url, json={"field": "value", "return_result": True, **fields})

    assert patch(value="current").status_code == 200
    assert patch(reconciliation=match, expected_value="current", expected_reconciliation=None).status_code == 200
    checkpoint = batch / "checkpoint.json"
    confirmed = checkpoint.read_bytes()
    assert patch(value="stale", expected_value="old", expected_reconciliation=match).status_code == 409
    assert patch(value="stale", expected_value="current", expected_reconciliation=None).status_code == 409
    assert checkpoint.read_bytes() == confirmed

    response = patch(value="reviewed", expected_value="current", expected_reconciliation=match)
    assert response.status_code == 200
    saved = response.json()["result"]
    assert saved["data"]["value"] == "old"
    assert saved["edited_data"]["value"] == "reviewed"
    assert saved["validation"]["value"]["reconciliation"] is None


def test_manual_confirmation_undo_restores_previous_match_only_if_confirmation_is_current(client, batch):
    url = f"/api/v1/batches/{batch.name}/results/old.jpg"
    before = {"uri": "https://example.invalid/gnd/before", "picked_by": "manual"}
    selected = {"uri": "https://example.invalid/gnd/selected", "picked_by": "manual"}

    def patch(**fields):
        return client.patch(url, json={"field": "value", "return_result": True, **fields})

    assert patch(reconciliation=before, expected_value="old", expected_reconciliation=None).status_code == 200
    assert patch(reconciliation=selected, expected_value="old", expected_reconciliation=before).status_code == 200

    checkpoint = batch / "checkpoint.json"
    confirmed = checkpoint.read_bytes()
    assert patch(value="old", reconciliation=before,
                 expected_value="old", expected_reconciliation=before).status_code == 409
    assert checkpoint.read_bytes() == confirmed

    assert patch(value="old", reconciliation=before,
                 expected_value="old", expected_reconciliation=selected).status_code == 200
    reloaded, _ = read_checkpoint(checkpoint)
    assert reloaded[0]["data"]["value"] == "old"
    assert reloaded[0]["edited_data"]["value"] == "old"
    assert reloaded[0]["validation"]["value"]["reconciliation"] == before
