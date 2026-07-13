"""WebSocket handshake auth tests (W-04/H-4)."""
import pytest
from starlette.websockets import WebSocketDisconnect


def test_ws_rejects_foreign_origin(client):
    """A cross-site Origin must be closed with policy-violation code 1008."""
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(
            "/api/v1/ws/task/some-batch",
            headers={"origin": "http://evil.example.com"},
        ):
            pass
    assert exc.value.code == 1008


def test_ws_accepts_allowed_origin(client):
    """An allow-listed Origin completes the handshake."""
    with client.websocket_connect(
        "/api/v1/ws/task/some-batch",
        headers={"origin": "http://localhost:5173"},
    ) as ws:
        # Connection accepted; no state yet for this batch, so just close.
        assert ws is not None


def test_ws_rejects_missing_token_when_enabled(client, auth_token):
    """With AUTH_TOKEN set, a handshake without ?token= is rejected even from an
    allowed origin."""
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(
            "/api/v1/ws/task/some-batch",
            headers={"origin": "http://localhost:5173"},
        ):
            pass
    assert exc.value.code == 1008


def test_ws_accepts_valid_token(client, auth_token):
    with client.websocket_connect(
        f"/api/v1/ws/task/some-batch?token={auth_token}",
        headers={"origin": "http://localhost:5173"},
    ) as ws:
        assert ws is not None
