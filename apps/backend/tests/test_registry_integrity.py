"""SAR-04c production registry transactions and failure boundaries."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.core import atomic_io, transactions
from app.core.config import settings
from app.core.registry import RegistryError, write_registry
from app.core.transactions import Resource, TransactionError
from app.models.schemas import TemplateCreate, TemplateUpdate
from app.services.batch_manager import batch_manager
from app.services.template_service import template_service
from test_error_disclosure import SECRET, assert_safe
from test_error_disclosure import isolated_state as isolated_state


@pytest.fixture(autouse=True)
def registry_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "BATCHES_HISTORY_FILE", str(tmp_path / "batches.json"))
    monkeypatch.setattr(template_service, "templates_file", tmp_path / "templates.json")


def create_template(name="one"):
    return template_service.create_template(TemplateCreate(name=name, fields=["value"]))


def seed(kind):
    if kind == "history":
        batch_manager._record_history("one", "One")
        return Path(settings.BATCHES_HISTORY_FILE)
    create_template()
    return template_service.templates_file


def mutate(kind):
    if kind == "history":
        batch_manager._record_history("two", "Two")
    else:
        create_template("two")


@pytest.mark.parametrize("kind", ["history", "template"])
@pytest.mark.parametrize("fault", ["json", "null", "row", "duplicate", "nonfinite", "unreadable"])
def test_invalid_registry_cannot_be_overwritten(kind, fault, monkeypatch, caplog):
    path = seed(kind)
    rows = json.loads(path.read_text())
    nonfinite = [dict(rows[0], opaque=float("nan"))]
    payload = {"nonfinite": json.dumps(nonfinite), "json": '{'+SECRET, "null": "null", "row": "[{}]", "duplicate": json.dumps(rows+rows), "unreadable": path.read_text()}[fault]
    path.write_text(payload)
    import app.core.registry as registry
    original_open = registry.os.open
    def open_file(filename, *args, **kwargs):
        if Path(filename) == path:
            raise PermissionError(SECRET)
        return original_open(filename, *args, **kwargs)
    if fault == "unreadable":
        monkeypatch.setattr(registry.os, "open", open_file)
    with pytest.raises(RegistryError) as error:
        mutate(kind)
    assert error.value.code == ("registry_unreadable" if fault == "unreadable" else "registry_invalid")
    monkeypatch.undo()
    # Read without any patched IO; fixture settings are no longer needed.
    assert path.read_text() == payload
    assert_safe(caplog, error.value)


@pytest.mark.parametrize("kind", ["history", "template"])
@pytest.mark.parametrize("fault", ["fdopen", "write", "flush", "fsync", "replace", "directory"])
def test_atomic_failure_cleanup_and_commit_boundary(kind, fault, monkeypatch, caplog):
    path = seed(kind)
    path.chmod(0o640)
    before = path.read_bytes()
    original_fsync = atomic_io.os.fsync
    calls = 0
    def sync(fd):
        nonlocal calls
        calls += 1
        if calls == (2 if fault == "directory" else 1):
            raise OSError(SECRET)
        return original_fsync(fd)
    if fault == "fdopen":
        monkeypatch.setattr(atomic_io.os, "fdopen", Mock(side_effect=OSError(SECRET)))
    elif fault in {"fsync", "directory"}:
        monkeypatch.setattr(atomic_io.os, "fsync", sync)
    elif fault == "replace":
        monkeypatch.setattr(atomic_io.os, "replace", Mock(side_effect=OSError(SECRET)))
    else:
        original_fdopen = atomic_io.os.fdopen
        class Stream:
            def __init__(self, stream):
                self.stream = stream
            def __enter__(self):
                return self
            def __exit__(self, *args):
                self.stream.close()
            def write(self, value):
                if fault == "write":
                    raise OSError(SECRET)
                return self.stream.write(value)
            def flush(self):
                raise OSError(SECRET)
            def fileno(self):
                return self.stream.fileno()
        monkeypatch.setattr(atomic_io.os, "fdopen", lambda *a, **k: Stream(original_fdopen(*a, **k)))
    with pytest.raises(RegistryError) as error:
        mutate(kind)
    assert error.value.code == ("registry_durability_uncertain" if fault == "directory" else "registry_write_failed")
    if fault == "directory":
        assert len(json.loads(path.read_text())) == 2
    else:
        assert path.read_bytes() == before
    assert path.stat().st_mode & 0o777 == 0o640
    assert not list(path.parent.glob(f".{path.name}.*.tmp"))
    assert_safe(caplog, error.value)


@pytest.mark.parametrize("kind", ["history", "template"])
@pytest.mark.parametrize("value", [object(), float("nan")])
def test_serialization_failure_preserves_old_registry(kind, caplog, value):
    path = seed(kind)
    before = path.read_bytes()
    payload = json.loads(path.read_text())
    payload[0]["opaque"] = value
    validate = batch_manager._validate_history if kind == "history" else template_service._validate
    with pytest.raises(RegistryError) as error:
        write_registry(path, payload, validate)
    assert error.value.code == "registry_write_failed"
    assert path.read_bytes() == before
    assert not list(path.parent.glob(f".{path.name}.*.tmp"))
    assert_safe(caplog, error.value)


@pytest.mark.parametrize("kind", ["history", "template_same", "template_different"])
def test_concurrent_mutations_retain_both_updates(kind, monkeypatch):
    batch_manager._record_history("one", "One")
    batch_manager._record_history("two", "Two")
    first_template = create_template()
    second_template = create_template("second") if kind == "template_different" else first_template
    entered, release, contended = threading.Event(), threading.Event(), threading.Event()
    owner = batch_manager if kind == "history" else template_service
    method = "_read_history_raw" if kind == "history" else "_read_templates"
    original = getattr(owner, method)
    first = True
    def read():
        nonlocal first
        value = original()
        if first:
            first = False
            entered.set()
            assert release.wait(5)
        return value
    monkeypatch.setattr(owner, method, read)
    real_flock = transactions.fcntl.flock
    def flock(fd, flags):
        try:
            return real_flock(fd, flags)
        except BlockingIOError:
            contended.set()
            raise
    monkeypatch.setattr(transactions.fcntl, "flock", flock)
    def change(which):
        if kind == "history":
            batch_manager.update_batch_status("one" if which == 1 else "two", "completed")
        elif which == 1:
            template_service.update_template(first_template.id, TemplateUpdate(name="changed"))
        else:
            template_service.update_template(second_template.id, TemplateUpdate(prompt_template="kept"))
    with ThreadPoolExecutor(2) as pool:
        a = pool.submit(change, 1)
        assert entered.wait(5)
        b = pool.submit(change, 2)
        try:
            assert contended.wait(5) and not b.done()
        finally:
            release.set()
        a.result(5)
        b.result(5)
    if kind == "history":
        assert all(row["status"] == "completed" and row["completed_at"] for row in original())
    else:
        assert template_service.get_template(first_template.id).name == "changed"
        assert template_service.get_template(second_template.id).prompt_template == "kept"


def test_template_gate_is_independent_of_history_and_batches():
    coordinator = batch_manager._registry_coordinator()
    entered, release = threading.Event(), threading.Event()
    def hold():
        entered.set()
        assert release.wait(5)
    with ThreadPoolExecutor(2) as pool:
        holder = pool.submit(coordinator.run_sync, [Resource.batch("one"), Resource.history()], hold)
        assert entered.wait(5)
        try:
            assert pool.submit(create_template).result(3).name == "one"
        finally:
            release.set()
        holder.result(5)


@pytest.mark.parametrize("kind", ["history", "template"])
def test_lock_timeout_never_mutates_registry(kind, monkeypatch, caplog, client):
    path = seed(kind)
    before = path.read_bytes()
    coordinator = batch_manager._registry_coordinator()
    entered, release = threading.Event(), threading.Event()
    resource = Resource.history() if kind == "history" else Resource.templates()
    def hold():
        entered.set()
        assert release.wait(5)
    with ThreadPoolExecutor(1) as pool:
        holder = pool.submit(coordinator.run_sync, [resource], hold)
        assert entered.wait(5)
        coordinator.timeout = 0
        monkeypatch.setattr(batch_manager, "_registry_coordinator", lambda: coordinator)
        try:
            with pytest.raises(TransactionError) as error:
                mutate(kind)
            assert error.value.code == "transaction_timeout"
            if kind == "template":
                response = client.post("/api/v1/templates/", json={"name":"blocked", "fields":["value"]})
                assert response.status_code == 409
                assert response.json()["error_code"] == "transaction_timeout"
                assert_safe(caplog, response.text)
        finally:
            release.set()
        holder.result(5)
    assert path.read_bytes() == before
    assert_safe(caplog, error.value)


@pytest.mark.parametrize("outer", [Resource.history(), Resource.templates()])
def test_registry_reentrance_and_template_combination_rejected(outer):
    coordinator = batch_manager._registry_coordinator()
    with pytest.raises(TransactionError) as error:
        coordinator.run_sync([outer], lambda: create_template() if outer.kind == "history" else batch_manager._record_history("one", "One"))
    assert error.value.code == "transaction_lock_order"


@pytest.mark.parametrize("endpoint,filename", [("/api/v1/batches/history", "history"), ("/api/v1/templates/", "template")])
def test_public_registry_errors_are_neutral(client, endpoint, filename, caplog):
    path = Path(settings.BATCHES_HISTORY_FILE) if filename == "history" else template_service.templates_file
    path.write_text('{'+SECRET)
    response = client.get(endpoint)
    assert response.status_code == 500
    assert response.json()["error_code"] == "registry_invalid"
    assert response.headers["x-request-id"]
    assert_safe(caplog, response.text)


@pytest.mark.parametrize("operation", ["delete", "purge"])
def test_corrupt_history_blocks_deletion_before_filesystem_change(operation):
    path = seed("history")
    path.write_text('{'+SECRET)
    batch = batch_manager.batches_dir / "one"
    batch.mkdir()
    (batch / "card.jpg").write_bytes(b"original")
    change = batch_manager.delete_batch if operation == "delete" else batch_manager.purge_batch_data
    with pytest.raises(RegistryError):
        change("one")
    assert path.read_text() == '{'+SECRET
    assert (batch / "card.jpg").read_bytes() == b"original"


@pytest.mark.parametrize("kind", ["history", "template"])
def test_absent_and_valid_empty_registries_are_distinct_from_corruption(kind):
    path = Path(settings.BATCHES_HISTORY_FILE) if kind == "history" else template_service.templates_file
    read = batch_manager._read_history_raw if kind == "history" else template_service._read_templates
    assert not path.exists() and read() == []
    assert not path.exists()  # No initialisation write on read.
    path.write_text('[]')
    assert read() == []
    mode = path.stat().st_mode & 0o777
    mutate(kind)
    assert len(read()) == 1
    assert path.stat().st_mode & 0o777 == mode


def test_new_registry_mode_is_private():
    seed("history")
    assert Path(settings.BATCHES_HISTORY_FILE).stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("kind", ["history", "template"])
def test_same_registry_reentrance_is_rejected(kind):
    resource = Resource.history() if kind == "history" else Resource.templates()
    with pytest.raises(TransactionError) as error:
        batch_manager._registry_coordinator().run_sync([resource], lambda: mutate(kind))
    assert error.value.code == "transaction_lock_order"


def test_concurrent_idempotent_seed_is_single_insert(monkeypatch):
    entered, release, contended = threading.Event(), threading.Event(), threading.Event()
    real_read = template_service._read_templates
    first = True
    def read():
        nonlocal first
        value = real_read()
        if first:
            first = False
            entered.set()
            assert release.wait(5)
        return value
    monkeypatch.setattr(template_service, "_read_templates", read)
    real_flock = transactions.fcntl.flock
    def flock(fd, flags):
        try:
            return real_flock(fd, flags)
        except BlockingIOError:
            contended.set()
            raise
    monkeypatch.setattr(transactions.fcntl, "flock", flock)
    def seed_named():
        return template_service.ensure_named(TemplateCreate(name="seed", fields=["value"]))
    with ThreadPoolExecutor(2) as pool:
        a = pool.submit(seed_named)
        assert entered.wait(5)
        b = pool.submit(seed_named)
        try:
            assert contended.wait(5)
        finally:
            release.set()
        assert a.result(5) is True and b.result(5) is False
    assert len(template_service.list_templates()) == 1


def test_history_write_failure_never_reports_completed_ocr(monkeypatch, caplog):
    import asyncio
    from unittest.mock import AsyncMock
    from app.api.api_v1.endpoints import batches
    from app.core.registry import RegistryWriteError
    from app.services.ocr_engine import ocr_engine
    from app.services.ws_manager import ws_manager
    seed("history")
    path = batch_manager.batches_dir / "one"
    path.mkdir()
    (path / "config.json").write_text('{"provider":"ollama","fields":["value"]}')
    monkeypatch.setattr(batches, "_resolve_provider", lambda *_: ("unused", "mock", None))
    monkeypatch.setattr(ocr_engine, "process_batch", AsyncMock(return_value=[]))
    monkeypatch.setattr(batch_manager, "_persist_history", Mock(side_effect=RegistryWriteError()))
    assert batch_manager.acquire_batch_lock("one")
    with pytest.raises(RegistryWriteError):
        asyncio.run(batches.run_ocr_task("one"))
    assert ws_manager.batch_states["one"].status == "failed"
    assert not batch_manager.is_run_active("one")
    assert batch_manager._read_history_raw()[0]["status"] == "uploaded"
    assert_safe(caplog, ws_manager.batch_states["one"])


def test_bulk_import_cancellation_joins_history_and_preserves_association(monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock
    from app.api.api_v1.endpoints import batches
    from app.services import bulk_orchestrator as bulk
    from app.services.bulk_manager import bulk_manager
    from test_error_disclosure import make_run
    run = make_run()
    run["folders"][0].update(batch_name=None, status="pending")
    bulk_manager.save_run(run)
    entered, release = threading.Event(), threading.Event()
    def materialise(*args, **kwargs):
        batch_manager._record_history("created", "Created")
        entered.set()
        assert release.wait(5)
        return {"batch_name":"created", "images_total":1}
    monkeypatch.setattr(bulk.bulk_import, "materialise_folder", materialise)
    ocr = AsyncMock()
    monkeypatch.setattr(batches, "run_ocr_task", ocr)
    async def scenario():
        task = asyncio.create_task(bulk._process_folder(run["bulk_run_id"], 0))
        assert await asyncio.to_thread(entered.wait, 3)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    try:
        asyncio.run(scenario())
    finally:
        release.set()
    assert bulk_manager.get_run(run["bulk_run_id"])["folders"][0]["batch_name"] == "created"
    assert batch_manager._read_history_raw()[0]["batch_name"] == "created"
    ocr.assert_not_called()


@pytest.mark.parametrize("kind", ["history", "template"])
def test_public_mutation_cannot_replace_corrupt_registry(kind, client, caplog):
    path = seed(kind)
    path.write_text('{'+SECRET)
    if kind == "history":
        batch = batch_manager.batches_dir / "one"
        batch.mkdir()
        response = client.delete("/api/v1/batches/one")
        assert batch.exists()
    else:
        response = client.post("/api/v1/templates/", json={"name":"blocked", "fields":["value"]})
    assert response.status_code == 500
    assert response.json()["error_code"] == "registry_invalid"
    assert path.read_text() == '{'+SECRET
    assert_safe(caplog, response.text)


@pytest.mark.parametrize("operation", ["create", "purge"])
def test_other_history_mutations_preserve_public_error_code(operation, client, caplog):
    import uuid
    path = seed("history")
    path.write_text('{'+SECRET)
    if operation == "purge":
        batch = batch_manager.batches_dir / "one"
        batch.mkdir()
        response = client.post("/api/v1/batches/one/purge")
        assert batch.exists()
    else:
        session_id = str(uuid.uuid4())
        session = batch_manager.get_temp_session_path(session_id)
        (session / "card.jpg").write_bytes(b"image")
        response = client.post("/api/v1/batches/", json={"session_id":session_id, "custom_name":"blocked", "fields":["value"]})
    assert response.status_code == 500
    assert response.json()["error_code"] == "registry_invalid"
    assert path.read_text() == '{'+SECRET
    assert_safe(caplog, response.text)


@pytest.mark.parametrize("phase", ["normal", "before_decision", "during_commit", "after_commit"])
def test_terminal_decision_survives_late_cancel(phase, monkeypatch, caplog):
    import asyncio
    from app.api.api_v1.endpoints import batches
    from app.services.ocr_engine import ocr_engine
    from app.services.ws_manager import ws_manager
    seed("history")
    batch = batch_manager.batches_dir / "one"
    batch.mkdir()
    (batch / "config.json").write_text('{"provider":"ollama","fields":["value"]}')
    (batch / "card.jpg").write_bytes(b"image")
    monkeypatch.setattr(batches, "_resolve_provider", lambda *_: ("unused", "mock", None))
    monkeypatch.setattr(ocr_engine, "_process_card_sync", lambda image, *a, **k: {"filename":image.name, "batch":batch.name, "success":True, "duration":0, "data":{"value":"mock"}})
    entered, release = threading.Event(), threading.Event()
    real_persist = batch_manager._persist_history
    real_process = ocr_engine.process_batch
    real_broadcast = ws_manager.broadcast_progress
    terminal_events = []
    async def process(*args, **kwargs):
        value = await real_process(*args, **kwargs)
        if phase == "before_decision":
            assert ws_manager.cancel_batch("one")
        return value
    def persist(history):
        if phase == "during_commit":
            entered.set()
            assert release.wait(5)
        real_persist(history)
        if phase == "after_commit":
            entered.set()
            assert release.wait(5)
    async def broadcast(name, state):
        if state.status in {"completed", "cancelled", "failed"}:
            terminal_events.append(state.status)
        return await real_broadcast(name, state)
    monkeypatch.setattr(ocr_engine, "process_batch", process)
    monkeypatch.setattr(batch_manager, "_persist_history", persist)
    monkeypatch.setattr(ws_manager, "broadcast_progress", broadcast)
    assert batch_manager.acquire_batch_lock("one")
    async def scenario():
        task = asyncio.create_task(batches.run_ocr_task("one"))
        if phase in {"during_commit", "after_commit"}:
            try:
                assert await asyncio.to_thread(entered.wait, 3)
                assert batch_manager.is_run_active("one")
                assert ws_manager.cancel_batch("one")
                assert not terminal_events
            finally:
                release.set()
        await task
    try:
        asyncio.run(scenario())
    finally:
        release.set()
    expected = "cancelled" if phase == "before_decision" else "completed"
    assert batch_manager._read_history_raw()[0]["status"] == expected
    assert ws_manager.batch_states["one"].status == expected
    assert terminal_events == [expected]
    assert not batch_manager.is_run_active("one")
    assert_safe(caplog, terminal_events)


@pytest.mark.parametrize("kind", ["history", "template"])
@pytest.mark.parametrize("file_type", ["symlink", "dangling", "directory", "fifo"])
def test_registry_rejects_links_and_special_files(kind, file_type, client, caplog):
    import os
    path = seed(kind)
    original = path.read_bytes()
    target = path.with_name("original.json")
    path.rename(target)
    if file_type == "symlink":
        path.symlink_to(target)
    elif file_type == "dangling":
        path.symlink_to(path.with_name("missing.json"))
    elif file_type == "directory":
        path.mkdir()
    else:
        os.mkfifo(path)
    read = batch_manager._read_history_raw if kind == "history" else template_service._read_templates
    for action in (read, lambda: mutate(kind)):
        with pytest.raises(RegistryError) as error:
            action()
        assert error.value.code == "registry_file_type_invalid"
    # The lower-level commit path must also reject a link before replacing it.
    validate = batch_manager._validate_history if kind == "history" else template_service._validate
    with pytest.raises(RegistryError):
        write_registry(path, json.loads(original), validate)
    endpoint = "/api/v1/batches/history" if kind == "history" else "/api/v1/templates/"
    response = client.get(endpoint)
    assert response.status_code == 500
    assert response.json()["error_code"] == "registry_file_type_invalid"
    assert target.read_bytes() == original
    if file_type in {"symlink", "dangling"}:
        assert path.is_symlink()
    assert not list(path.parent.glob(f".{path.name}.*.tmp"))
    assert_safe(caplog, response.text, error.value)


def registry_client_at_prefix(prefix, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.api_v1.api import api_router
    from app.main import registry_exception_handler

    monkeypatch.setattr(settings, "API_V1_STR", prefix)
    test_app = FastAPI()
    test_app.include_router(api_router, prefix=settings.API_V1_STR)
    test_app.add_exception_handler(TransactionError, registry_exception_handler)
    return TestClient(test_app)


@pytest.mark.parametrize("prefix", ["/api/v1", "/custom/api"])
@pytest.mark.parametrize("failure", ["open", "sync", "close", "sync_close"])
def test_public_template_post_replace_reconciliation(failure, prefix, monkeypatch, caplog):
    import os
    import stat
    client = registry_client_at_prefix(prefix, monkeypatch)
    endpoint = f"{prefix}/templates/"
    # Identical names are permitted; they are not idempotency keys.
    first = client.post(endpoint, json={"name":"same", "fields":["value"]})
    assert first.status_code == 201
    before = {entry["id"] for entry in client.get(endpoint).json()}
    real_open, real_sync, real_close = os.open, os.fsync, os.close
    real_replace = os.replace
    directory_fds = set()
    calls = []
    def open_file(path, flags, *args, **kwargs):
        if flags & os.O_DIRECTORY:
            if failure == "open":
                raise OSError(SECRET)
            fd = real_open(path, flags, *args, **kwargs)
            directory_fds.add(fd)
            return fd
        return real_open(path, flags, *args, **kwargs)
    def sync(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode) and failure in {"sync", "sync_close"}:
            raise OSError(SECRET)
        return real_sync(fd)
    def close(fd):
        directory = fd in directory_fds
        directory_fds.discard(fd)
        real_close(fd)
        if directory and failure in {"close", "sync_close"}:
            raise OSError(SECRET)  # Cleanup reports failure after a successful fsync.
    def replace(*args):
        calls.append("replace")
        return real_replace(*args)
    monkeypatch.setattr(atomic_io.os, "open", open_file)
    monkeypatch.setattr(atomic_io.os, "fsync", sync)
    monkeypatch.setattr(atomic_io.os, "close", close)
    monkeypatch.setattr(atomic_io.os, "replace", replace)
    response = client.post(endpoint, json={"name":"same", "fields":["value"]})
    assert response.status_code == 500
    body = response.json()
    assert body["error_code"] == ("registry_directory_close_failed" if failure == "close" else "registry_durability_uncertain")
    assert body["commit_status"] == ("applied" if failure == "close" else "uncertain")
    assert body["retryable"] is False
    assert "Do not repeat" in body["detail"] and "checking the current state" in body["detail"]
    assert response.headers["x-request-id"]
    assert str(template_service.templates_file.parent) not in response.text
    # Follow the prescribed read/compare path; do not POST a second time.
    assert body["reconcile_url"] == endpoint
    read = client.get(body["reconcile_url"])
    assert read.status_code == 200
    after = read.json()
    assert len(after) == 2 and len({entry["id"] for entry in after} - before) == 1
    assert [entry["name"] for entry in after] == ["same", "same"]
    assert client.get(body["reconcile_url"]).json() == after
    assert calls == ["replace"] and not directory_fds
    assert not list(template_service.templates_file.parent.glob(".templates.json.*.tmp"))
    assert_safe(caplog, response.text, read.text)


def test_history_recovery_url_resolves_at_custom_prefix(monkeypatch):
    from app.core.registry import RegistryDurabilityError

    prefix = "/custom/api"
    client = registry_client_at_prefix(prefix, monkeypatch)
    seed("history")
    (batch_manager.batches_dir / "one").mkdir()
    persist = batch_manager._persist_history

    def persist_then_report_uncertain(history):
        persist(history)
        raise RegistryDurabilityError()

    monkeypatch.setattr(batch_manager, "_persist_history", persist_then_report_uncertain)
    response = client.post(f"{prefix}/batches/one/purge")
    assert response.status_code == 500
    assert response.json()["reconcile_url"] == f"{prefix}/batches/history"
    assert response.json()["retryable"] is False
    history = client.get(response.json()["reconcile_url"])
    assert history.status_code == 200
    assert history.json()[0]["status"] == "purged"


@pytest.mark.parametrize("replacement", ["symlink", "fifo"])
def test_registry_open_rejects_type_swap_after_preflight(replacement, monkeypatch):
    import os
    from app.core import registry
    path = seed("history")
    backup = path.with_name("saved.json")
    original = path.read_bytes()
    real_check = registry.check_regular_target
    def check(target):
        real_check(target)
        if target == path:
            path.rename(backup)
            if replacement == "symlink":
                path.symlink_to(backup)
            else:
                os.mkfifo(path)
    monkeypatch.setattr(registry, "check_regular_target", check)
    with pytest.raises(RegistryError) as error:
        batch_manager._read_history_raw()
    assert error.value.code == "registry_file_type_invalid"
    assert backup.read_bytes() == original
