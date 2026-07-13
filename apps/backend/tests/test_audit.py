"""Audit log tests (audit finding I-2)."""
import json

from app.core import audit
from app.core.config import settings


def _read_audit_lines():
    with open(settings.AUDIT_LOG_FILE, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_actor_unknown_without_trusted_proxy(client, monkeypatch):
    """A client-supplied user header is IGNORED when the request is not from a
    configured trusted proxy — actor must not be a fabricated identity."""
    monkeypatch.setattr(settings, "AUTH_TOKEN", "tok")
    monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", "")  # trust no proxy
    # Force an auth failure so an audit record is written, with a spoofed identity.
    r = client.get(
        "/api/v1/batches/",
        headers={"X-Forwarded-User": "attacker@evil", "Authorization": "Bearer wrong"},
    )
    assert r.status_code == 401
    rec = _read_audit_lines()[-1]
    assert rec["action"] == "auth.failure"
    assert rec["result"] == "failure"
    assert rec["actor"] == audit.ACTOR_UNKNOWN  # spoofed header not trusted


def test_actor_trusted_when_proxy_ip_allowed(client, monkeypatch):
    """When the request's client IP is a trusted proxy, the SSO header is honored."""
    monkeypatch.setattr(settings, "AUTH_TOKEN", "tok")
    # TestClient's default client host is "testclient"; override trust to match.
    monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", "testclient")

    # _ip_trusted uses ipaddress parsing; "testclient" is not an IP, so simulate a
    # real proxy IP instead by patching the client host via headers is not possible.
    # Instead assert the negative path is covered above and the header-name is honored
    # through resolve_actor with a trusted IP unit-style:
    monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", "1.2.3.4")

    class FakeReq:
        client = ("1.2.3.4", 5)
        headers = {settings.AUDIT_USER_HEADER: "curator@lib"}

    assert audit.resolve_actor(FakeReq()) == "curator@lib"


def test_custom_header_name_honored(monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", "10.0.0.5")
    monkeypatch.setattr(settings, "AUDIT_USER_HEADER", "X-Remote-User")

    class FakeReq:
        client = ("10.0.0.5", 1)
        headers = {"X-Remote-User": "alice"}

    assert audit.resolve_actor(FakeReq()) == "alice"


def test_no_sensitive_fields_logged(monkeypatch, tmp_path):
    """log_event only records the fields we pass — no token/secret leakage."""
    monkeypatch.setattr(settings, "AUDIT_LOG_FILE", str(tmp_path / "a.jsonl"))
    audit.log_event("batch.start", target="b1", provider="ollama")
    with open(settings.AUDIT_LOG_FILE, encoding="utf-8") as f:
        rec = json.loads(f.readline())
    assert set(rec) >= {"ts", "actor", "action", "target", "result", "request_id", "source_ip"}
    assert rec["provider"] == "ollama"
    # No token/authorization keys ever present.
    assert not any("token" in k.lower() or "auth" in k.lower() for k in rec)
