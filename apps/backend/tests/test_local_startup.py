import sys
from unittest.mock import Mock

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route, WebSocketRoute
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import local
from app.core.config import Settings, default_env_file
from app.core.security import check_ws_auth, require_auth


async def http(request):
    await require_auth(request, authorization=None)
    return PlainTextResponse("ok")


async def websocket(socket):
    if not check_ws_auth(socket):
        await socket.close(1008)
        return
    await socket.accept()
    await socket.send_text("ok")
    await socket.close()


@pytest.fixture
def local_app():
    return local.LocalAccess(Starlette(routes=[
        Route("/api", http),
        Route("/batches-static/card.jpg", http),
        Route("/download.csv", http),
        WebSocketRoute("/ws", websocket),
    ]))


@pytest.mark.parametrize("path", ["/api", "/batches-static/card.jpg", "/download.csv"])
def test_local_access_requires_real_loopback_peer_and_local_headers(local_app, monkeypatch, path):
    monkeypatch.setattr(local.settings, "AUTH_TOKEN", "synthetic-legacy-token")
    with TestClient(local_app, base_url="http://127.0.0.1:5173", client=("127.0.0.1", 12345)) as client:
        assert client.get(path, headers={"origin": "http://127.0.0.1:5173"}).status_code == 200
        assert client.get(path, headers={"origin": "https://outside.invalid"}).status_code == 403
        assert client.get(path, headers={"host": "outside.invalid:5173"}).status_code == 403
    with TestClient(local_app, base_url="http://127.0.0.1:5173", client=("192.0.2.1", 12345)) as client:
        assert client.get(path, headers={
            "forwarded": "for=127.0.0.1",
            "x-forwarded-for": "127.0.0.1",
        }).status_code == 403


def test_local_websocket_checks_origin(local_app):
    with TestClient(local_app, base_url="http://127.0.0.1:5173", client=("127.0.0.1", 12345)) as client:
        with client.websocket_connect("ws://127.0.0.1:5173/ws", headers={"origin": "http://127.0.0.1:5173"}) as conn:
            assert conn.receive_text() == "ok"
        with pytest.raises(WebSocketDisconnect), client.websocket_connect("ws://127.0.0.1:5173/ws", headers={"origin": "https://outside.invalid"}):
            pass


def test_launcher_rejects_non_loopback_host(monkeypatch, capsys):
    run = Mock()
    monkeypatch.setattr(local.uvicorn, "run", run)
    monkeypatch.setattr(local.settings, "HOST", "0.0.0.0")
    monkeypatch.setattr(sys, "argv", ["local"])
    with pytest.raises(SystemExit):
        local.main()
    run.assert_not_called()
    assert "HOST=127.0.0.1" in capsys.readouterr().err


def test_env_file_precedence_and_endpoint_resolution(monkeypatch, tmp_path):
    env_file = tmp_path / "selected.env"
    env_file.write_text(
        "API_BASE_URL=http://file.invalid/v1/\n"
        "OLLAMA_API_ENDPOINT=http://ollama.invalid/v1/chat/completions\n"
        "GPUSTACK_BASE_URL=http://gpustack.invalid/\n"
        "GPUSTACK_DEFAULT_MODEL=demo-vlm\n"
    )
    monkeypatch.setenv("INDEXCARDS_ENV_FILE", str(env_file))
    monkeypatch.setenv("API_BASE_URL", "http://process.invalid/v1/")
    monkeypatch.delenv("API_ENDPOINT", raising=False)
    monkeypatch.chdir(tmp_path)
    settings = Settings(_env_file=default_env_file())
    assert settings.API_ENDPOINT == "http://process.invalid/v1/chat/completions"
    assert settings.OLLAMA_MODELS_ENDPOINT == "http://ollama.invalid/v1/models"
    assert settings.GPUSTACK_API_ENDPOINT == "http://gpustack.invalid/v1/chat/completions"
    assert settings.GPUSTACK_DEFAULT_MODEL == "demo-vlm"
    monkeypatch.setenv("API_ENDPOINT", "http://explicit.invalid/custom")
    assert Settings(_env_file=default_env_file()).API_ENDPOINT == "http://explicit.invalid/custom"
