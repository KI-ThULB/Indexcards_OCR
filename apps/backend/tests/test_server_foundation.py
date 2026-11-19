import asyncio
import hashlib
from concurrent.futures import ThreadPoolExecutor

import pytest
from argon2 import PasswordHasher, Type
from pydantic import SecretStr
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import _application
from app.core.sessions import OperatorPassword, SessionCapacityError, SessionStore
from app.main import app as legacy_app
from app.server import ServerSettings, app, validate_public_origin


@pytest.fixture(scope="module")
def operator_hash():
    return PasswordHasher(memory_cost=19 * 1024, time_cost=2, parallelism=1).hash("synthetic test password")


@pytest.mark.parametrize("origin", ["https://indexcards.example", "https://localhost:8443", "https://[::1]:8443"])
def test_canonical_https_origin(origin):
    validate_public_origin(origin)


@pytest.mark.parametrize("origin", [
    "", "http://indexcards.example", "https://indexcards.example/", "https://indexcards.example?",
    "https://indexcards.example#fragment", "https://user:secret@indexcards.example",
    "https://indexcards.example:443", "https://indexcards.example:0", "https://indexcards.example:65536",
    "https://indexcards.example\n", "https://indexcards.example,https://other.example",
    "https://indexcards.example\\other", "https://indexcards.example.", "https://127.1",
    "https://INDEXCARDS.example", "https://[fe80::1%25scope]", "https://ex_ample.invalid",
])
def test_reject_unsafe_or_ambiguous_origins(origin):
    with pytest.raises(ValueError, match="one canonical HTTPS origin"):
        validate_public_origin(origin)


def test_operator_password_validation(operator_hash):
    operator = OperatorPassword(SecretStr(operator_hash))
    assert operator.verify("synthetic test password")
    assert not operator.verify("incorrect")
    assert not operator.verify("")
    assert not operator.verify("x" * 1025)


@pytest.mark.parametrize("encoded_hash", [
    "", "malformed-test-credential",
    PasswordHasher(memory_cost=8, time_cost=1, parallelism=1, type=Type.I).hash("synthetic"),
    PasswordHasher(memory_cost=8, time_cost=1, parallelism=1).hash("synthetic"),
])
def test_invalid_hash_is_rejected_without_echoing_input(encoded_hash):
    with pytest.raises(ValueError) as raised:
        OperatorPassword(SecretStr(encoded_hash))
    assert str(raised.value) == "Invalid operator password hash"


def test_malformed_encoding_and_expensive_parameters(operator_hash):
    for modified in [operator_hash[:-1] + "!", operator_hash.replace("m=19456", "m=1048576")]:
        with pytest.raises(ValueError, match="Invalid operator password hash"):
            OperatorPassword(SecretStr(modified))


def test_session_digest_expiry_revocation_and_restart():
    now = 100.0
    store = SessionStore(ttl_seconds=5, capacity=2, clock=lambda: now)
    first = store.create()
    second = store.create()
    assert len(first) == 43 and first != second
    assert set(store._expires_at) == {hashlib.sha256(value.encode()).digest() for value in (first, second)}
    assert store.is_active(first)
    assert not store.is_active("not-a-session")
    assert not SessionStore(ttl_seconds=5, capacity=2).is_active(first)
    assert store.revoke(first)
    assert not store.revoke(first)
    assert not store.is_active(first)
    now = 105.0
    assert not store.is_active(second)


def test_session_capacity_and_expired_slot_reuse():
    now = 0.0
    store = SessionStore(ttl_seconds=3, capacity=1, clock=lambda: now)
    with ThreadPoolExecutor(max_workers=2) as executor:
        attempts = [executor.submit(store.create) for _ in range(2)]
    assert sum(isinstance(future.exception(), SessionCapacityError) for future in attempts) == 1
    first = next(future.result() for future in attempts if future.exception() is None)
    assert store.is_active(first)
    now = 3.0
    assert store.is_active(store.create()) and not store.is_active(first)


def test_settings_limits_and_password_repr(operator_hash):
    settings = ServerSettings(
        _env_file=None, SERVER_PUBLIC_ORIGIN="https://indexcards.example",
        SERVER_OPERATOR_PASSWORD_HASH=SecretStr(operator_hash),
        SERVER_SESSION_CAPACITY=1,
    )
    operator, store = settings.build_authentication()
    assert operator.verify("synthetic test password") and store.is_active(store.create())
    assert operator_hash not in repr(settings)


@pytest.mark.parametrize("configuration, expected", [
    ({}, "Invalid server configuration"),
    ({"SERVER_PUBLIC_ORIGIN": "http://outside.invalid"}, "Invalid server configuration"),
    ({"SERVER_OPERATOR_PASSWORD_HASH": "invalid-private-value"}, "Invalid server configuration"),
    ({"SERVER_SESSION_TTL_SECONDS": "0"}, "Invalid server configuration"),
    ({"SERVER_SESSION_CAPACITY": "4097"}, "Invalid server configuration"),
    ({"SERVER_SESSION_CAPACITY": "invalid-private-value"}, "Invalid server configuration"),
    ({}, "Server profile disabled until Phase B2"),
])
def test_startup_never_succeeds(tmp_path, monkeypatch, operator_hash, configuration, expected):
    empty = tmp_path / "empty.env"
    empty.touch()
    monkeypatch.setenv("INDEXCARDS_ENV_FILE", str(empty))
    for name in ServerSettings.model_fields:
        monkeypatch.delenv(name, raising=False)
    if configuration or expected.startswith("Server profile"):
        monkeypatch.setenv("SERVER_PUBLIC_ORIGIN", "https://indexcards.example")
        monkeypatch.setenv("SERVER_OPERATOR_PASSWORD_HASH", operator_hash)
    for name, value in configuration.items():
        monkeypatch.setenv(name, value)
    messages = []

    async def receive():
        return {"type": "lifespan.startup"}

    async def send(message):
        messages.append(message)

    asyncio.run(app({"type": "lifespan"}, receive, send))
    assert [message["type"] for message in messages] == ["lifespan.startup.failed"]
    assert expected in messages[0]["message"]
    assert operator_hash not in messages[0]["message"]
    assert "invalid-private-value" not in messages[0]["message"]


def test_public_entrypoints_refuse_without_lifespan():
    assert legacy_app is app
    client = TestClient(legacy_app)  # Outside a context manager, lifespan does not run.
    for path in ("/", "/api/v1/config", "/docs", "/batches-static/example/card.jpg", "/api/v1/bulk/runs/example/export.csv"):
        response = client.get(path, headers={
            "Forwarded": "for=127.0.0.1;proto=https",
            "X-Forwarded-User": "operator",
        })
        assert response.status_code == 503
    with pytest.raises(WebSocketDisconnect) as refused, client.websocket_connect("/api/v1/ws/task/example"):
        pass
    assert refused.value.code == 1008



def test_internal_application_is_not_a_bare_asgi_entrypoint():
    assert not hasattr(_application, "app")
    assert not hasattr(_application, "_app")
    with pytest.raises(TypeError):
        _application._create_application()
