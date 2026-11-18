"""SAR-02 lifecycle tests using the installed Uvicorn h11 ASGI server cycle."""

import asyncio
import json
import logging
from unittest.mock import Mock

import h11
import pytest
from starlette.responses import FileResponse
from starlette.websockets import WebSocketDisconnect
from uvicorn.protocols.http.flow_control import FlowControl
from uvicorn.protocols.http.h11_impl import RequestResponseCycle

from app.core.config import settings
from conftest import app
from app.models.schemas import BatchProgress
from app.services import bulk_export
from app.services.batch_manager import batch_manager
from app.services.ws_manager import ws_manager
from test_error_disclosure import SECRET, assert_safe, make_run
from test_error_disclosure import isolated_state as isolated_state


async def server_request(path, *, headers=None, application=app):
    """Real h11 framing + Uvicorn exception handling, with an in-memory transport."""
    transport = Mock()
    wire = []
    transport.write.side_effect = wire.append
    transport.is_closing.return_value = False
    conn = h11.Connection(h11.SERVER)
    conn.receive_data(f"GET {path} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode())
    conn.next_event()
    conn.next_event()
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": headers or [],
        "client": ("127.0.0.1", 1234),
        "server": ("localhost", 8000),
        "state": {},
    }
    cycle = RequestResponseCycle(
        scope=scope,
        conn=conn,
        transport=transport,
        flow=FlowControl(transport),
        logger=logging.getLogger("uvicorn.error"),
        access_logger=logging.getLogger("uvicorn.access"),
        access_log=False,
        default_headers=[],
        message_event=asyncio.Event(),
        on_response=lambda: None,
    )
    cycle.message_event.set()
    messages = []

    async def recorded(scope, receive, send):
        async def record(message):
            messages.append(message)
            await send(message)

        await application(scope, receive, record)

    await cycle.run_asgi(recorded)
    return cycle, transport, messages, b"".join(wire)


@pytest.mark.parametrize("kind", ["stream", "file"])
def test_late_export_failure_aborts_without_server_traceback(
    monkeypatch, tmp_path, caplog, kind
):
    run = make_run()
    rid = run["bulk_run_id"]
    monkeypatch.setattr(settings, "BULK_IMPORT_ROOT", str(batch_manager.batches_dir))
    monkeypatch.setattr(settings, "AUDIT_ENABLED", True)
    audit = tmp_path / "audit.jsonl"
    monkeypatch.setattr(settings, "AUDIT_LOG_FILE", str(audit))
    if kind == "stream":

        def broken(_run):
            yield "header\r\n"
            raise RuntimeError(SECRET)

        monkeypatch.setattr(bulk_export, "iter_failures_csv", broken)
        suffix = "failures.csv"
    else:

        async def broken_file(self, send, send_header_only, send_pathsend):
            assert not send_pathsend
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": self.raw_headers,
                }
            )
            await send(
                {"type": "http.response.body", "body": b"partial", "more_body": True}
            )
            raise OSError(SECRET)

        monkeypatch.setattr(FileResponse, "_handle_simple", broken_file)
        suffix = "export.csv"
    cycle, transport, messages, wire = asyncio.run(
        server_request(f"/api/v1/bulk/runs/{rid}/{suffix}")
    )
    assert cycle.response_started and not cycle.response_complete
    assert messages[0]["type"] == "http.response.start"
    assert any(m.get("body") for m in messages[1:])
    assert not any(
        m["type"] == "http.response.body" and not m.get("more_body", False)
        for m in messages
    )
    transport.close.assert_called_once()
    assert b"0\r\n\r\n" not in wire  # No successful chunked end marker.
    assert "ASGI callable returned without completing response" in caplog.text
    assert "code=http_delivery_failed" in caplog.text
    records = [json.loads(line) for line in audit.read_text().splitlines()]
    assert [r["result"] for r in records if r["action"] == "bulk_run_exported"] == [
        "failure"
    ]
    headers = dict(messages[0]["headers"])
    identifier = headers[b"x-request-id"].decode()
    assert identifier in caplog.text
    assert records[-1]["request_id"] == identifier
    assert_safe(caplog, wire, records)


@pytest.mark.parametrize("suffix", ["export.csv", "failures.csv"])
def test_successful_export_completes_before_success_audit(
    monkeypatch, tmp_path, caplog, suffix
):
    run = make_run()
    monkeypatch.setattr(settings, "BULK_IMPORT_ROOT", str(batch_manager.batches_dir))
    monkeypatch.setattr(settings, "AUDIT_ENABLED", True)
    audit = tmp_path / "audit.jsonl"
    monkeypatch.setattr(settings, "AUDIT_LOG_FILE", str(audit))
    cycle, transport, messages, wire = asyncio.run(
        server_request(f"/api/v1/bulk/runs/{run['bulk_run_id']}/{suffix}")
    )
    assert cycle.response_complete
    transport.close.assert_not_called()
    assert messages[-1]["type"] == "http.response.body" and not messages[-1].get(
        "more_body", False
    )
    records = [json.loads(line) for line in audit.read_text().splitlines()]
    assert [r["result"] for r in records] == ["success"]
    assert "http_delivery_failed" not in caplog.text
    assert_safe(caplog, wire, records)


def test_actual_ws_replay_after_accept_closes_with_reference(
    client, monkeypatch, caplog
):
    progress = BatchProgress(
        batch_name="replay", current=1, total=2, percentage=50, status="running"
    )
    ws_manager.batch_states["replay"] = progress

    def broken_json(*args, **kwargs):
        raise RuntimeError(SECRET)

    monkeypatch.setattr(BatchProgress, "json", broken_json)
    with client.websocket_connect("/api/v1/ws/task/replay") as socket:
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_text()
    assert closed.value.code == 1011
    assert "Reference:" in closed.value.reason
    identifier = closed.value.reason.split("Reference: ")[1]
    assert identifier in caplog.text
    assert "replay" not in ws_manager.active_connections
    assert_safe(caplog, closed.value.reason)


def test_global_diagnostic_reference_does_not_trust_input(client, monkeypatch, caplog):
    def broken():
        raise RuntimeError(SECRET)

    monkeypatch.setattr(batch_manager, "get_history", broken)
    response = client.get("/api/v1/batches/history", headers={"X-Request-ID": SECRET})
    assert response.status_code == 500
    identifier = response.headers["x-request-id"]
    assert len(identifier) == 32 and identifier in caplog.text
    assert "code=http_unhandled operation=http.handle" in caplog.text
    assert_safe(caplog, response.text, response.headers)


@pytest.mark.parametrize(
    "provider, code",
    [
        ("", "provider_missing"),
        (SECRET, "provider_unknown"),
        ("gpustack", "provider_disabled"),
    ],
)
def test_provider_error_has_safe_code_and_request_reference(
    client, monkeypatch, caplog, provider, code
):
    (batch_manager.batches_dir / "test").mkdir()
    monkeypatch.setattr(settings, "GPUSTACK_ENABLED", False)
    response = client.post("/api/v1/batches/test/start", json={"provider": provider})
    assert response.status_code == 400
    assert f"code={code} operation=batch.start" in caplog.text
    assert response.headers["x-request-id"] in caplog.text
    assert_safe(caplog, response.text)


@pytest.mark.parametrize(
    "error, code, status",
    [
        (ValueError(SECRET), "authority_configuration_invalid", 503),
        (RuntimeError(SECRET), "authority_request_failed", 502),
    ],
)
def test_authority_error_has_diagnostic_reference(
    client, monkeypatch, caplog, error, code, status
):
    from unittest.mock import AsyncMock
    from app.services.authority import wikidata

    monkeypatch.setattr(settings, "BATCHES_DIR", str(batch_manager.batches_dir))
    (batch_manager.batches_dir / "test").mkdir()
    monkeypatch.setattr(wikidata, "search_wikidata", AsyncMock(side_effect=error))
    response = client.post(
        "/api/v1/reconcile",
        json={"authority": "wikidata", "query": SECRET, "batch_name": "test"},
    )
    assert response.status_code == status
    assert f"code={code} operation=authority.reconcile" in caplog.text
    assert response.headers["x-request-id"] in caplog.text
    assert_safe(caplog, response.text)


def test_bulk_structural_code_and_run_reference_are_logged(monkeypatch, caplog):
    from unittest.mock import AsyncMock
    from app.services import bulk_orchestrator

    run = make_run()
    monkeypatch.setattr(
        bulk_orchestrator,
        "_drive_folders",
        AsyncMock(
            side_effect=bulk_orchestrator.StructuralError(
                SECRET, code="checkpoint_failed"
            )
        ),
    )
    asyncio.run(bulk_orchestrator._drive(run["bulk_run_id"]))
    assert "code=checkpoint_failed operation=bulk.drive" in caplog.text
    assert f"correlation_id={run['bulk_run_id']}" in caplog.text
    assert_safe(caplog)


def test_body_final_frame_is_withheld_when_background_task_fails(caplog):
    from starlette.background import BackgroundTask
    from starlette.responses import Response
    from app.core.delivery import DeliveryErrorBoundary

    def broken():
        raise RuntimeError(SECRET)

    async def application(scope, receive, send):
        await Response(b"partial", background=BackgroundTask(broken))(
            scope, receive, send
        )

    cycle, transport, messages, wire = asyncio.run(
        server_request("/", application=DeliveryErrorBoundary(application))
    )
    assert cycle.response_started and not cycle.response_complete
    transport.close.assert_called_once()
    assert len(messages) == 1  # Final body was withheld, not passed as a success.
    assert_safe(caplog, wire)


def test_json_command_completes_before_long_background_work(caplog):
    from starlette.background import BackgroundTask
    from starlette.responses import JSONResponse
    from app.core.delivery import DeliveryErrorBoundary

    observed = []

    async def scenario():
        delivered = asyncio.Event()

        async def work():
            assert delivered.is_set(), "Command response must not wait for the OCR task"
            observed.append("work")

        async def application(scope, receive, send):
            await JSONResponse({"status": "started"}, background=BackgroundTask(work))(
                scope, receive, send
            )

        boundary = DeliveryErrorBoundary(application)

        async def wrapper(scope, receive, send):
            async def watched(message):
                await send(message)
                if message["type"] == "http.response.body" and not message.get(
                    "more_body", False
                ):
                    delivered.set()

            await boundary(scope, receive, watched)

        return await server_request("/", application=wrapper)

    cycle, transport, messages, wire = asyncio.run(scenario())
    assert cycle.response_complete and observed == ["work"]
    assert "http_background_failed" not in caplog.text
    assert_safe(caplog, wire)
