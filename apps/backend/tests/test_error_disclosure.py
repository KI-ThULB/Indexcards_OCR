"""SAR-02: synthetic exception secrets must not cross diagnostic boundaries."""

import asyncio
import json
import logging
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.api.api_v1.endpoints import batches, ws
from app.services import bulk_orchestrator, bulk_progress, bulk_export
from app.services.bulk_manager import bulk_manager, FOLDER_RUNNING, STATUS_RUNNING
from app.services.batch_manager import batch_manager
from app.services.validation import corrector
from app.services.ws_manager import ConnectionManager, ws_manager
from app.models.schemas import BatchProgress

SECRET = "PRIVATE_OCR_TOKEN_https://user:password@example.invalid/?key=SECRET"


def fail(*args, **kwargs):
    raise RuntimeError(SECRET)


def assert_safe(caplog, *values):
    assert SECRET not in caplog.text
    assert all(SECRET not in str(value) for value in values)
    assert all(
        record.exc_info is None and not record.exc_text for record in caplog.records
    )


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch, tmp_path, caplog):
    caplog.set_level(logging.DEBUG, logger="app")
    monkeypatch.setattr(settings, "AUTH_TOKEN", "")
    monkeypatch.setattr(settings, "AUDIT_ENABLED", False)
    monkeypatch.setattr(batch_manager, "batches_dir", tmp_path / "batches")
    batch_manager.batches_dir.mkdir()
    monkeypatch.setattr(bulk_manager, "runs_dir", tmp_path / "runs")
    for name in ("batch_states", "bulk_states", "active_connections", "cancel_events"):
        monkeypatch.setattr(ws_manager, name, {})


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError(SECRET),
        corrector.requests.HTTPError(SECRET),
        json.JSONDecodeError(SECRET, SECRET, 0),
    ],
)
def test_corrector_does_not_disclose_exception(monkeypatch, caplog, error):
    monkeypatch.setattr(settings, "CORRECTOR_PROVIDER", "openrouter")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "synthetic-key")
    monkeypatch.setattr(corrector.requests, "post", Mock(side_effect=error))
    result = corrector.invoke_corrector(
        "field", "value", {}, {"used": 0, "cap": 1}, "unused"
    )
    assert result["status"] == "invalid"
    assert_safe(caplog, result)
    assert "exception_type=" in caplog.text


@pytest.mark.parametrize("existing", [False, True])
def test_background_error_is_safe_in_websocket_replay(
    monkeypatch, client, caplog, existing
):
    name = "disclosure_batch"
    path = batch_manager.batches_dir / name
    path.mkdir()
    (path / "config.json").write_text('{"provider":"ollama"}')
    monkeypatch.setattr(
        batches.ocr_engine, "process_batch", AsyncMock(side_effect=RuntimeError(SECRET))
    )
    if existing:
        ws_manager.batch_states[name] = BatchProgress(
            batch_name=name, current=1, total=2, percentage=50, status="running"
        )
    asyncio.run(batches.run_ocr_task(name))
    with client.websocket_connect(f"/api/v1/ws/task/{name}") as socket:
        state = socket.receive_json()
    assert state["status"] == "failed"
    assert not batch_manager.is_run_active(name)
    assert name not in ws_manager.cancel_events
    assert_safe(caplog, state)
    assert "RuntimeError" in caplog.text


def test_global_500_has_no_traceback_or_exception(monkeypatch, caplog):
    monkeypatch.setattr(batch_manager, "get_history", fail)
    with TestClient(app) as client:
        response = client.get("/api/v1/batches/history")
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert_safe(caplog, response.text)
    assert "RuntimeError" in caplog.text


def make_run():
    return bulk_manager.create_run(
        name="test",
        template_id="test-template",
        schema_fields=["field"],
        provider="ollama",
        model="model",
        folders=[{"source_folder": "folder", "images_total": 1}],
    )


@pytest.mark.parametrize(
    "error", [RuntimeError(SECRET), bulk_orchestrator.StructuralError(SECRET)]
)
def test_bulk_failure_safe_on_disk_api_and_ws(monkeypatch, client, caplog, error):
    run = make_run()
    rid = run["bulk_run_id"]
    run.update(status=STATUS_RUNNING, current_folder="folder")
    run["folders"][0]["status"] = FOLDER_RUNNING
    bulk_manager.save_run(run)
    monkeypatch.setattr(
        bulk_orchestrator, "_drive_folders", AsyncMock(side_effect=error)
    )
    monkeypatch.setattr(settings, "BULK_IMPORT_ROOT", str(batch_manager.batches_dir))
    asyncio.run(bulk_orchestrator._drive(rid))
    response = client.get(f"/api/v1/bulk/runs/{rid}")
    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["folders"][0]["status"] == "failed"
    with client.websocket_connect(f"/api/v1/ws/task/bulk:{rid}") as socket:
        state = socket.receive_json()
    assert_safe(
        caplog,
        response.text,
        state,
        (bulk_manager.run_dir(rid) / "run.json").read_text(),
    )


def test_bulk_start_conflict_does_not_echo_exception(monkeypatch, client, caplog):
    run = make_run()
    monkeypatch.setattr(settings, "BULK_IMPORT_ROOT", str(batch_manager.batches_dir))
    monkeypatch.setattr(
        bulk_orchestrator, "start_run", AsyncMock(side_effect=RuntimeError(SECRET))
    )
    response = client.post(f"/api/v1/bulk/runs/{run['bulk_run_id']}/start")
    assert response.status_code == 409
    assert_safe(caplog, response.text)


def test_bulk_export_error_has_no_traceback(monkeypatch, client, caplog):
    run = make_run()
    monkeypatch.setattr(settings, "BULK_IMPORT_ROOT", str(batch_manager.batches_dir))
    monkeypatch.setattr(bulk_export, "write_consolidated_csv", fail)
    response = client.get(f"/api/v1/bulk/runs/{run['bulk_run_id']}/export.csv")
    assert response.status_code == 500
    assert_safe(caplog, response.text)


def test_bulk_progress_error_has_no_traceback(monkeypatch, caplog):
    monkeypatch.setattr(bulk_progress, "to_progress", fail)
    run = make_run()
    assert bulk_progress.publish_bulk_progress(run["bulk_run_id"]) is None
    assert_safe(caplog)


@pytest.mark.parametrize("is_bulk", [False, True])
def test_ws_send_error_does_not_log_exception(caplog, is_bulk):
    manager = ConnectionManager()
    socket = Mock(send_text=AsyncMock(side_effect=RuntimeError(SECRET)))
    manager.active_connections["channel"] = [socket]
    progress = Mock(json=Mock(return_value="{}"))
    send = manager.broadcast_bulk_progress if is_bulk else manager.broadcast_progress
    asyncio.run(send("channel", progress))
    assert_safe(caplog)
    assert "RuntimeError" in caplog.text


def test_ws_receive_error_does_not_log_payload_or_exception(monkeypatch, caplog):
    socket = Mock(
        scope={"type": "websocket", "state": {}},
        close=AsyncMock(),
        receive_text=AsyncMock(side_effect=[SECRET, RuntimeError(SECRET)]),
    )
    monkeypatch.setattr(ws, "check_ws_auth", lambda _: True)
    monkeypatch.setattr(ws_manager, "connect", AsyncMock())
    disconnect = Mock()
    monkeypatch.setattr(ws_manager, "disconnect", disconnect)
    asyncio.run(ws.websocket_endpoint(socket, "test"))
    disconnect.assert_called_once_with(socket, "test")
    assert_safe(caplog)


@pytest.mark.parametrize("operation", ["read", "write"])
def test_engine_checkpoint_error_does_not_log_exception(
    monkeypatch, tmp_path, caplog, operation
):
    from app.services import ocr_engine as module

    path = tmp_path / "engine_batch"
    path.mkdir()
    (path / "card.jpg").write_bytes(b"image")
    (path / "checkpoint.json").write_text('{"results": [], "audit": []}')
    monkeypatch.setattr(module, "read_checkpoint_snapshot" if operation == "read" else "write_checkpoint", fail)
    monkeypatch.setattr(
        module.ocr_engine,
        "_process_card_sync",
        lambda image, batch, *a, **k: {
            "filename": image.name,
            "batch": batch,
            "success": True,
            "duration": 0,
            "data": {},
        },
    )
    from app.core.checkpoint import CheckpointError

    with pytest.raises(CheckpointError) as error:
        asyncio.run(module.ocr_engine.process_batch(path, fields=["field"]))
    assert_safe(caplog, error.value)


def test_retry_checkpoint_failure_does_not_log_exception(monkeypatch, client, caplog):
    name = "retry_batch"
    path = batch_manager.batches_dir / name
    (path / "_errors").mkdir(parents=True)
    (path / "_errors" / "card.jpg").write_bytes(b"image")
    (path / "checkpoint.json").write_text("{}")
    monkeypatch.setattr(batches, "read_checkpoint", fail)
    monkeypatch.setattr(batches, "run_ocr_task", AsyncMock())
    response = client.post(f"/api/v1/batches/{name}/retry-image/card.jpg")
    assert response.status_code == 500
    assert (path / "_errors" / "card.jpg").exists()
    assert not (path / "card.jpg").exists()
    batches.run_ocr_task.assert_not_called()
    assert_safe(caplog, response.text)


@pytest.mark.parametrize("kind", ["provider", "background"])
def test_bulk_classification_never_relays_card_error(monkeypatch, caplog, kind):
    run = make_run()
    rid = run["bulk_run_id"]
    name = "classified_batch"
    path = batch_manager.batches_dir / name
    path.mkdir()
    from app.core.checkpoint import write_checkpoint

    write_checkpoint(
        path / "checkpoint.json",
        [{"filename": "card.jpg", "success": False, "error": "HTTP 401 " + SECRET}],
        [],
    )
    if kind == "background":
        ws_manager.batch_states[name] = BatchProgress(
            batch_name=name,
            current=0,
            total=1,
            percentage=0,
            status="failed",
            error=SECRET,
        )
    with pytest.raises(bulk_orchestrator.StructuralError) as error:
        bulk_orchestrator._classify_folder(rid, 0, name)
    assert_safe(caplog, str(error.value))
    if kind == "provider":
        assert error.value.code == "provider_refused"


def test_bulk_checkpoint_export_error_does_not_log_traceback(monkeypatch, caplog):
    path = batch_manager.batches_dir / "export_batch"
    path.mkdir()
    (path / "checkpoint.json").write_text("{}")
    monkeypatch.setattr(bulk_export, "read_checkpoint", fail)
    from app.core.checkpoint import CheckpointError
    with pytest.raises(CheckpointError) as error:
        bulk_export._folder_results("export_batch")
    assert_safe(caplog, error.value)


def test_bulk_state_read_error_does_not_log_traceback(monkeypatch, caplog):
    run = make_run()
    import app.services.bulk_manager as module

    monkeypatch.setattr(module.json, "load", Mock(side_effect=ValueError(SECRET)))
    assert bulk_manager.get_run(run["bulk_run_id"]) is None
    assert_safe(caplog)


def test_bulk_send_wrapper_does_not_log_traceback(monkeypatch, caplog):
    monkeypatch.setattr(
        ws_manager,
        "broadcast_bulk_progress",
        AsyncMock(side_effect=RuntimeError(SECRET)),
    )
    asyncio.run(bulk_progress._send("bulk:test", Mock()))
    assert_safe(caplog)


@pytest.mark.parametrize(
    "error, status", [(ValueError(SECRET), 400), (RuntimeError(SECRET), 500)]
)
def test_batch_creation_errors_are_safe(monkeypatch, client, caplog, error, status):
    monkeypatch.setattr(batch_manager, "create_batch", Mock(side_effect=error))
    response = client.post(
        "/api/v1/batches/",
        json={
            "custom_name": "test",
            "session_id": "00000000-0000-0000-0000-000000000000",
        },
    )
    assert response.status_code == status
    assert_safe(caplog, response.text)


def test_manual_purge_error_does_not_log_traceback(monkeypatch, client, caplog):
    monkeypatch.setattr(batch_manager, "purge_batch_data", fail)
    response = client.post("/api/v1/batches/test/purge")
    assert response.status_code == 500
    assert_safe(caplog, response.text)


@pytest.mark.parametrize(
    "error, status", [(ValueError(SECRET), 503), (RuntimeError(SECRET), 502)]
)
def test_reconcile_errors_are_safe(monkeypatch, client, caplog, error, status):
    from app.services.authority import wikidata

    monkeypatch.setattr(settings, "BATCHES_DIR", str(batch_manager.batches_dir))
    (batch_manager.batches_dir / "test").mkdir()
    monkeypatch.setattr(wikidata, "search_wikidata", AsyncMock(side_effect=error))
    response = client.post(
        "/api/v1/reconcile",
        json={"authority": "wikidata", "query": "test", "batch_name": "test"},
    )
    assert response.status_code == status
    assert_safe(caplog, response.text)


def test_ws_replay_error_does_not_escape_to_asgi_server(monkeypatch, caplog):
    monkeypatch.setattr(ws, "check_ws_auth", lambda _: True)
    monkeypatch.setattr(
        ws_manager, "connect", AsyncMock(side_effect=RuntimeError(SECRET))
    )
    disconnect = Mock()
    monkeypatch.setattr(ws_manager, "disconnect", disconnect)
    socket = Mock(scope={"type": "websocket", "state": {}}, close=AsyncMock())
    asyncio.run(ws.websocket_endpoint(socket, "test"))
    disconnect.assert_called_once_with(socket, "test")
    assert_safe(caplog)


def test_resize_failure_keeps_fallback_without_logging_exception(
    monkeypatch, tmp_path, caplog
):
    import base64
    from app.services import ocr_engine as module

    image = tmp_path / "card.jpg"
    image.write_bytes(b"synthetic-image")
    monkeypatch.setattr(module.Image, "open", fail)
    encoded = module.ocr_engine._encode_image_to_base64(image)
    assert base64.b64decode(encoded) == b"synthetic-image"
    assert_safe(caplog)


def test_retention_failure_is_safe_in_response_and_logs(monkeypatch, caplog):
    from app.services import retention

    monkeypatch.setattr(settings, "RETENTION_DAYS", 1)
    monkeypatch.setattr(
        retention,
        "preview_purgeable",
        lambda: {"eligible": [{"batch_name": "test", "age_days": 2}]},
    )
    monkeypatch.setattr(batch_manager, "purge_batch_data", fail)
    result = retention.run_retention_sweep()
    assert result["errors"][0]["error"] == "Retention purge failed"
    assert_safe(caplog, result)


def test_audit_write_failure_does_not_log_traceback(monkeypatch, tmp_path, caplog):
    from app.core import audit

    monkeypatch.setattr(settings, "AUDIT_ENABLED", True)
    monkeypatch.setattr(settings, "AUDIT_LOG_FILE", str(tmp_path / "audit.jsonl"))
    monkeypatch.setattr(audit, "open", fail, raising=False)
    audit.log_event("batch.start", target="test")
    assert "Failed to write audit record" in caplog.text
    assert_safe(caplog)
