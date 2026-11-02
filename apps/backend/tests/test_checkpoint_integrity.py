"""SAR-03a: reject corrupted state and retain the last durable checkpoint."""

import asyncio
import json
import threading
from unittest.mock import Mock

import pytest

from app.api.api_v1.endpoints import batches
from app.core import atomic_io
from app.core.checkpoint import (
    CheckpointInvalidError,
    CheckpointReadError,
    CheckpointWriteError,
    read_checkpoint,
    write_checkpoint,
)
from app.core.config import settings
from app.services import ocr_engine as engine_module
from app.services.batch_manager import batch_manager
from app.services.ws_manager import ws_manager
from test_error_disclosure import SECRET, assert_safe


def row(filename="old.jpg"):
    return {
        "filename": filename,
        "success": True,
        "duration": 0,
        "data": {"value": "preserved"},
    }


def fail(*args, **kwargs):
    raise OSError(SECRET)


@pytest.mark.parametrize("content", [[], {"results": [], "audit": []}, {"results": []}])
def test_empty_compatible_formats_are_valid(tmp_path, content):
    path = tmp_path / "checkpoint.json"
    path.write_text(json.dumps(content))
    before = path.read_bytes(), path.stat().st_mtime_ns
    assert read_checkpoint(path) == ([], [])
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


def test_missing_is_distinct_from_invalid_and_empty(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_checkpoint(tmp_path / "checkpoint.json")


@pytest.mark.parametrize(
    "content",
    [
        None,
        1,
        "text",
        {},
        {"audit": []},
        {"results": None},
        {"results": {}},
        {"results": [None]},
        {"results": ["row"]},
        {"results": [{}]},
        {"results": [{"filename": "a.jpg", "success": "true"}]},
        {"results": [{"filename": "", "success": True}]},
        {"results": [row(), row()]},
        {"results": [dict(row(), data=[])]},
        {"results": [dict(row(), edited_data="text")]},
        {"results": [dict(row(), validation=[])]},
        {"results": [dict(row(), confidence=[])]},
        {"results": [], "audit": None},
        {"results": [], "audit": {}},
        {"results": [], "audit": "text"},
        {"results": [], "audit": [None]},
        {"results": [], "audit": ["event"]},
    ],
)
def test_invalid_structures_are_not_filtered_or_repaired(tmp_path, content):
    path = tmp_path / "checkpoint.json"
    path.write_text(json.dumps(content))
    original = path.read_bytes(), path.stat().st_mtime_ns
    with pytest.raises(CheckpointInvalidError) as error:
        read_checkpoint(path)
    assert str(error.value) == "checkpoint_invalid"
    assert (path.read_bytes(), path.stat().st_mtime_ns) == original


@pytest.mark.parametrize(
    "content", [b'{"results": [', b'{"' + SECRET.encode() + b'":', b"\xff"]
)
def test_corrupt_json_or_encoding_has_content_free_error(tmp_path, content, caplog):
    path = tmp_path / "checkpoint.json"
    path.write_bytes(content)
    with pytest.raises(CheckpointInvalidError) as error:
        read_checkpoint(path)
    assert path.read_bytes() == content
    assert_safe(caplog, error.value)


def test_unreadable_file_has_distinct_safe_error(tmp_path, monkeypatch, caplog):
    import app.core.checkpoint as module

    path = tmp_path / "checkpoint.json"
    path.write_text("[]")
    monkeypatch.setattr(
        module, "open", Mock(side_effect=PermissionError(SECRET)), raising=False
    )
    with pytest.raises(CheckpointReadError) as error:
        read_checkpoint(path)
    assert path.read_text() == "[]"
    assert error.value.code == "checkpoint_unreadable"
    assert_safe(caplog, error.value)


@pytest.mark.parametrize("stage", ["write", "flush", "close", "fsync", "replace"])
def test_atomic_failure_preserves_original_and_removes_temp(
    tmp_path, monkeypatch, caplog, stage
):
    path = tmp_path / "checkpoint.json"
    original = b'{"results": [], "audit": [{"id":"original"}]}'
    path.write_bytes(original)
    before = path.stat().st_mtime_ns
    if stage in {"write", "flush", "close"}:
        real_fdopen = atomic_io.os.fdopen

        class BrokenFile:
            def __init__(self, *args, **kwargs):
                self.file = real_fdopen(*args, **kwargs)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.file.close()
                if stage == "close":
                    raise OSError(28, SECRET)

            def write(self, content):
                if stage == "write":
                    self.file.write(content[:5])
                    raise OSError(28, SECRET)
                return self.file.write(content)

            def flush(self):
                if stage == "flush":
                    raise OSError(28, SECRET)
                return self.file.flush()

            def fileno(self):
                return self.file.fileno()

        monkeypatch.setattr(atomic_io.os, "fdopen", BrokenFile)
    else:
        monkeypatch.setattr(atomic_io.os, stage, Mock(side_effect=OSError(28, SECRET)))
    with pytest.raises(CheckpointWriteError) as error:
        write_checkpoint(path, [row()], [])
    assert path.read_bytes() == original and path.stat().st_mtime_ns == before
    assert list(tmp_path.iterdir()) == [path]
    assert_safe(caplog, error.value)


@pytest.fixture
def batch(tmp_path, monkeypatch, caplog):
    caplog.set_level("DEBUG", logger="app")
    monkeypatch.setattr(batch_manager, "batches_dir", tmp_path / "batches")
    batch_manager.batches_dir.mkdir()
    path = batch_manager.batches_dir / "integrity"
    path.mkdir()
    (path / "config.json").write_text('{"provider":"ollama"}')
    (path / "a.jpg").write_bytes(b"image")
    for name in ("batch_states", "bulk_states", "active_connections", "cancel_events"):
        monkeypatch.setattr(ws_manager, name, {})
    status = Mock()
    monkeypatch.setattr(batch_manager, "update_batch_status", status)
    return path, status


@pytest.mark.parametrize("mode", ["bad_json", "bad_results", "bad_audit", "unreadable"])
@pytest.mark.parametrize("resume", [True, False])
def test_resume_failure_keeps_file_and_sends_no_images(
    batch, monkeypatch, caplog, mode, resume
):
    path, status = batch
    checkpoint = path / "checkpoint.json"
    contents = {
        "bad_json": b'{"' + SECRET.encode(),
        "bad_results": b'{"results":[{}],"audit":[]}',
        "bad_audit": b'{"results":[],"audit":null}',
        "unreadable": b'{"results":[],"audit":[]}',
    }
    original = contents[mode]
    checkpoint.write_bytes(original)
    stamp = checkpoint.stat().st_mtime_ns
    provider = Mock(return_value=row("a.jpg"))
    monkeypatch.setattr(engine_module.ocr_engine, "_process_card_sync", provider)
    if mode == "unreadable":
        import app.core.checkpoint as module

        monkeypatch.setattr(
            module, "open", Mock(side_effect=PermissionError(SECRET)), raising=False
        )
    assert batch_manager.acquire_batch_lock(path.name)
    asyncio.run(batches.run_ocr_task(path.name, resume=resume))
    provider.assert_not_called()
    state = ws_manager.batch_states[path.name]
    assert state.status == "failed"
    assert "checkpoint_" in state.error
    assert (
        checkpoint.read_bytes() == original and checkpoint.stat().st_mtime_ns == stamp
    )
    assert not batch_manager.is_run_active(path.name)
    assert [call.args[1] for call in status.call_args_list] == ["failed"]
    assert_safe(caplog, state.model_dump())


@pytest.mark.parametrize("stage", ["write", "fsync", "replace"])
def test_ocr_persistence_failure_never_marks_completed(
    batch, monkeypatch, caplog, stage
):
    path, status = batch
    checkpoint = path / "checkpoint.json"
    write_checkpoint(checkpoint, [row()], [{"id": "original"}])
    original = checkpoint.read_bytes()
    monkeypatch.setattr(
        engine_module.ocr_engine,
        "_process_card_sync",
        lambda image, *a: row(image.name),
    )
    if stage == "write":
        monkeypatch.setattr(atomic_io, "atomic_write_text", fail)
    else:
        monkeypatch.setattr(atomic_io.os, stage, fail)
    assert batch_manager.acquire_batch_lock(path.name)
    asyncio.run(batches.run_ocr_task(path.name))
    state = ws_manager.batch_states[path.name]
    assert state.status == "failed" and "checkpoint_write_failed" in state.error
    assert [call.args[1] for call in status.call_args_list] == ["failed"]
    assert checkpoint.read_bytes() == original
    assert_safe(caplog, state.model_dump())


def test_failure_waits_for_inflight_provider_before_unlock(batch, monkeypatch, caplog):
    path, status = batch
    (path / "b.jpg").write_bytes(b"image")
    (path / "c.jpg").write_bytes(b"image")
    checkpoint = path / "checkpoint.json"
    write_checkpoint(checkpoint, [row()], [])
    original = checkpoint.read_bytes()
    second_started, release_second, failed = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )
    requests = []

    def process(image, *args):
        stop = args[-1]
        if image.name == "a.jpg":
            assert second_started.wait(5)
        elif image.name == "b.jpg":
            second_started.set()
            assert release_second.wait(5)
        else:
            assert failed.wait(5)
            assert stop.wait(5)
        if stop.is_set():
            return {"stopped": True}
        requests.append(image.name)
        return row(image.name)

    def broken_write(*args):
        failed.set()
        raise OSError(SECRET)

    monkeypatch.setattr(settings, "MAX_WORKERS", 2)
    monkeypatch.setattr(engine_module.ocr_engine, "_process_card_sync", process)
    monkeypatch.setattr(engine_module, "write_checkpoint", broken_write)
    assert batch_manager.acquire_batch_lock(path.name)

    async def scenario():
        task = asyncio.create_task(batches.run_ocr_task(path.name))
        try:
            assert await asyncio.to_thread(failed.wait, 5)
            assert await asyncio.to_thread(ws_manager.cancel_events[path.name].wait, 5)
            assert batch_manager.is_run_active(path.name) and not task.done()
            assert ws_manager.cancel_events[path.name].is_set()
            with pytest.raises(RuntimeError):
                batch_manager.delete_batch(path.name)
        finally:
            release_second.set()
            await asyncio.wait_for(task, 5)

    asyncio.run(scenario())
    assert "c.jpg" not in requests
    assert ws_manager.batch_states[path.name].status == "failed"
    assert not batch_manager.is_run_active(path.name)
    assert checkpoint.read_bytes() == original
    assert_safe(caplog)


def test_repeated_task_cancel_keeps_lock_until_writer_exits(batch, monkeypatch, caplog):
    path, status = batch
    checkpoint = path / "checkpoint.json"
    write_checkpoint(checkpoint, [], [])
    entered, release, exited = threading.Event(), threading.Event(), threading.Event()
    real_write = engine_module.write_checkpoint

    def slow_write(*args):
        entered.set()
        assert release.wait(5)
        try:
            return real_write(*args)
        finally:
            exited.set()

    monkeypatch.setattr(engine_module, "write_checkpoint", slow_write)
    monkeypatch.setattr(
        engine_module.ocr_engine,
        "_process_card_sync",
        lambda image, *a: row(image.name),
    )
    assert batch_manager.acquire_batch_lock(path.name)

    async def scenario():
        task = asyncio.create_task(batches.run_ocr_task(path.name))
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            for _ in range(2):
                task.cancel()
                await asyncio.sleep(0)
                assert not task.done() and batch_manager.is_run_active(path.name)
            with pytest.raises(RuntimeError):
                batch_manager.delete_batch(path.name)
        finally:
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 5)

    asyncio.run(scenario())
    assert exited.is_set() and not batch_manager.is_run_active(path.name)
    assert read_checkpoint(checkpoint)[0] == [row("a.jpg")]
    assert not any(call.args[1] == "completed" for call in status.call_args_list)
    assert_safe(caplog)


@pytest.mark.parametrize(
    "payload",
    [
        '{"results":[{"filename":"a.jpg","success":true}],"results":[],"audit":[]}',
        '{"results":[],"audit":[{"id":"keep"}],"audit":[]}',
        '[{"filename":"a.jpg","filename":"b.jpg","success":true}]',
        '{"results":[{"filename":"a.jpg","success":true,"data":{"value":1,"value":2}}],"audit":[]}',
        '{"results":[{"filename":"a.jpg","success":true,"validation":{"x":{"status":"valid","status":"invalid"}}}],"audit":[]}',
        '{"results":[],"audit":[{"' + SECRET + '":1,"' + SECRET + '":2}]}',
        '{"results":[],"resu\\u006cts":[{"filename":"a.jpg","success":true}],"audit":[]}',
    ],
)
def test_duplicate_keys_abort_resume_without_repair(
    batch, monkeypatch, caplog, payload
):
    path, status = batch
    json.loads(payload)  # Valid JSON syntax; the ambiguity itself must be rejected.
    checkpoint = path / "checkpoint.json"
    checkpoint.write_text(payload)
    original, stamp = checkpoint.read_bytes(), checkpoint.stat().st_mtime_ns
    with pytest.raises(CheckpointInvalidError) as error:
        read_checkpoint(checkpoint)
    provider = Mock(return_value=row("a.jpg"))
    monkeypatch.setattr(engine_module.ocr_engine, "_process_card_sync", provider)
    assert batch_manager.acquire_batch_lock(path.name)
    asyncio.run(batches.run_ocr_task(path.name))
    provider.assert_not_called()
    assert (
        checkpoint.read_bytes() == original and checkpoint.stat().st_mtime_ns == stamp
    )
    assert ws_manager.batch_states[path.name].status == "failed"
    assert "checkpoint_invalid" in ws_manager.batch_states[path.name].error
    assert_safe(caplog, error.value, ws_manager.batch_states[path.name].model_dump())


@pytest.mark.parametrize("stage", ["write", "flush", "close", "fsync", "replace"])
@pytest.mark.parametrize("previous_completed", [False, True])
def test_cancellation_does_not_hide_persistence_failure(
    batch, monkeypatch, caplog, client, stage, previous_completed
):
    from app.models.schemas import BatchProgress

    path, _status = batch
    checkpoint = path / "checkpoint.json"
    write_checkpoint(checkpoint, [row()], [{"id": "keep"}])
    original = checkpoint.read_bytes()
    history = path.parent / "history.json"
    history.write_text(
        json.dumps(
            [
                {
                    "batch_name": path.name,
                    "status": "completed" if previous_completed else "running",
                }
            ]
        )
    )
    monkeypatch.setattr(settings, "BATCHES_HISTORY_FILE", str(history))
    monkeypatch.setattr(settings, "AUTH_TOKEN", "")
    monkeypatch.setattr(
        batch_manager,
        "update_batch_status",
        type(batch_manager).update_batch_status.__get__(batch_manager),
    )
    if previous_completed:
        ws_manager.batch_states[path.name] = BatchProgress(
            batch_name=path.name, current=1, total=1, percentage=100, status="completed"
        )
    entered, release, exited = threading.Event(), threading.Event(), threading.Event()

    def gated_failure(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        raise OSError(28, SECRET)

    # Scope this checkpoint fault to its actual writer. History now uses the
    # same atomic helper; its separate status commit is tested in SAR-04c.
    fault_owner = atomic_io if stage == "write" else atomic_io.os
    fault_attribute = "atomic_write_text" if stage == "write" else ("fdopen" if stage in {"flush", "close"} else stage)
    original_fault_target = getattr(fault_owner, fault_attribute)
    if stage in {"flush", "close"}:
        real_fdopen = atomic_io.os.fdopen

        class BrokenFile:
            def __init__(self, *args, **kwargs):
                self.file = real_fdopen(*args, **kwargs)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.file.close()
                if stage == "close":
                    gated_failure()

            def write(self, content):
                return self.file.write(content)

            def flush(self):
                if stage == "flush":
                    gated_failure()
                return self.file.flush()

            def fileno(self):
                return self.file.fileno()

        monkeypatch.setattr(atomic_io.os, "fdopen", BrokenFile)
    elif stage == "write":
        monkeypatch.setattr(atomic_io, "atomic_write_text", gated_failure)
    else:
        monkeypatch.setattr(atomic_io.os, stage, gated_failure)
    real_write = engine_module.write_checkpoint

    def tracked_write(*args):
        try:
            return real_write(*args)
        finally:
            monkeypatch.setattr(fault_owner, fault_attribute, original_fault_target)
            exited.set()

    monkeypatch.setattr(engine_module, "write_checkpoint", tracked_write)
    monkeypatch.setattr(
        engine_module.ocr_engine,
        "_process_card_sync",
        lambda image, *a: row(image.name),
    )
    original_release = batch_manager.release_batch_lock

    def checked_release(name):
        assert exited.is_set(), "Lock must outlive the actual writer"
        original_release(name)

    monkeypatch.setattr(batch_manager, "release_batch_lock", checked_release)
    assert batch_manager.acquire_batch_lock(path.name)

    async def scenario():
        task = asyncio.create_task(batches.run_ocr_task(path.name))
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            for _ in range(2):
                task.cancel()
                assert await asyncio.to_thread(
                    ws_manager.cancel_events[path.name].wait, 5
                )
                assert not task.done() and batch_manager.is_run_active(path.name)
            assert not batch_manager.acquire_batch_lock(path.name)
            with pytest.raises(RuntimeError):
                batch_manager.delete_batch(path.name)
        finally:
            release.set()
            # The confirmed write failure wins; run_ocr_task handles it as failed.
            await asyncio.wait_for(task, 5)

    asyncio.run(scenario())
    assert exited.is_set() and not batch_manager.is_run_active(path.name)
    assert json.loads(history.read_text())[0]["status"] == "failed"
    assert checkpoint.read_bytes() == original
    assert not list(path.glob(".checkpoint.json.*.tmp"))
    with client.websocket_connect(f"/api/v1/ws/task/{path.name}") as socket:
        state = socket.receive_json()
    assert state["status"] == "failed" and "checkpoint_write_failed" in state["error"]
    assert_safe(caplog, state)


def test_later_write_failure_preserves_successfully_saved_progress(
    batch, monkeypatch, caplog
):
    path, status = batch
    (path / "b.jpg").write_bytes(b"image")
    checkpoint = path / "checkpoint.json"
    write_checkpoint(checkpoint, [], [{"id": "keep"}])
    saved, release_second = threading.Event(), threading.Event()
    real_write = engine_module.write_checkpoint
    snapshot, attempts = [], []
    first_row = dict(row("a.jpg"), batch=path.name)

    def write_until_second(*args):
        attempts.append([item["filename"] for item in args[1]])
        if not saved.is_set():
            real_write(*args)
            snapshot.append(checkpoint.read_bytes())
            saved.set()
        else:
            raise OSError(SECRET)

    def process(image, *args):
        if image.name == "b.jpg":
            assert release_second.wait(5)
        return dict(row(image.name), batch=path.name)

    monkeypatch.setattr(settings, "MAX_WORKERS", 2)
    monkeypatch.setattr(engine_module, "write_checkpoint", write_until_second)
    monkeypatch.setattr(engine_module.ocr_engine, "_process_card_sync", process)
    assert batch_manager.acquire_batch_lock(path.name)

    async def scenario():
        task = asyncio.create_task(batches.run_ocr_task(path.name))
        try:
            assert await asyncio.to_thread(saved.wait, 5)
            assert read_checkpoint(checkpoint) == ([first_row], [{"id": "keep"}])
        finally:
            release_second.set()
            await asyncio.wait_for(task, 5)

    asyncio.run(scenario())
    assert checkpoint.read_bytes() == snapshot[0]
    assert read_checkpoint(checkpoint) == ([first_row], [{"id": "keep"}])
    assert attempts == [["a.jpg"], ["a.jpg", "b.jpg"]]
    assert ws_manager.batch_states[path.name].status == "failed"
    assert "checkpoint_write_failed" in ws_manager.batch_states[path.name].error
    assert [call.args[1] for call in status.call_args_list] == ["failed"]
    assert_safe(caplog)


def test_failure_status_precedes_cancellable_websocket_delivery(
    batch, monkeypatch, caplog
):
    from unittest.mock import AsyncMock
    from app.models.schemas import BatchProgress

    path, status = batch
    ws_manager.batch_states[path.name] = BatchProgress(
        batch_name=path.name, current=1, total=1, percentage=100, status="completed"
    )
    monkeypatch.setattr(
        engine_module.ocr_engine,
        "process_batch",
        AsyncMock(side_effect=CheckpointWriteError()),
    )
    assert batch_manager.acquire_batch_lock(path.name)

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        async def publish(name, state):
            entered.set()
            await release.wait()

        monkeypatch.setattr(ws_manager, "broadcast_progress", publish)
        task = asyncio.create_task(batches.run_ocr_task(path.name))
        await asyncio.wait_for(entered.wait(), 5)
        assert ws_manager.batch_states[path.name].status == "failed"
        status.assert_called_once_with(path.name, "failed")
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert not batch_manager.is_run_active(path.name)
    assert ws_manager.batch_states[path.name].status == "failed"
    assert_safe(caplog, ws_manager.batch_states[path.name].model_dump())
