"""Application security / access audit log (audit finding I-2).

Append-only JSON Lines log of security-relevant events, for accountability
(GDPR Art. 5(2)) and processing records (Art. 30). Deliberately minimal:

  - Logs ONLY security events (auth failures, batch start/cancel/delete,
    export, purge, config changes) — never OCR text, extracted metadata,
    uploads, prompts, API keys or bearer tokens.
  - Complements, never replaces, the reverse-proxy access log.
  - The actor is taken from a configurable trusted proxy header (SSO), and
    ONLY when the request actually arrives through a configured trusted proxy.
    Otherwise the actor is "unknown" (no fabricated identity).

Each record: {ts, actor, action, target, result, request_id, source_ip}.
"""
import ipaddress
import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import Request
from starlette.websockets import WebSocket

from app.core.config import settings

logger = logging.getLogger(__name__)

# Serialize writes so concurrent requests can't interleave partial JSON lines.
_write_lock = threading.Lock()

# Sentinels for the actor field when no trusted identity is available.
ACTOR_UNKNOWN = "unknown"
ACTOR_SERVICE = "service-account"


def _client_ip(scope_client) -> Optional[str]:
    """Immediate peer IP (the proxy, in production). scope_client is (host, port)."""
    if scope_client:
        return scope_client[0]
    return None


def _ip_trusted(ip: Optional[str]) -> bool:
    """True if `ip` matches one of the configured trusted proxy IPs/CIDRs."""
    if not ip:
        return False
    trusted = settings.trusted_proxy_ips
    if not trusted:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for entry in trusted:
        try:
            if "/" in entry:
                if addr in ipaddress.ip_network(entry, strict=False):
                    return True
            elif addr == ipaddress.ip_address(entry):
                return True
        except ValueError:
            continue
    return False


def resolve_actor(request: Request | WebSocket) -> str:
    """Resolve the authenticated actor for audit records.

    Trust the configured SSO header ONLY when the request comes through a
    configured trusted proxy. Any client-supplied identity header on a
    non-proxied request is ignored (the proxy is also expected to strip it —
    see DEPLOYMENT.md). Falls back to a non-identifying sentinel.
    """
    client = getattr(request, "client", None)
    ip = _client_ip(client)
    if _ip_trusted(ip):
        header_name = settings.AUDIT_USER_HEADER
        user = request.headers.get(header_name)
        if user:
            return user.strip()
    return ACTOR_UNKNOWN


def source_ip(request: Request | WebSocket) -> Optional[str]:
    """Best-effort source IP for the record. Prefer X-Forwarded-For's first hop
    when behind a trusted proxy, else the immediate peer."""
    client = getattr(request, "client", None)
    ip = _client_ip(client)
    if _ip_trusted(ip):
        xff = request.headers.get("X-Forwarded-For")
        if xff:
            return xff.split(",")[0].strip()
    return ip


def request_id(request: Request | WebSocket) -> str:
    """Correlation id: reuse an upstream request id header if present, else mint one."""
    for header in ("X-Request-Id", "X-Correlation-Id"):
        rid = request.headers.get(header)
        if rid:
            return rid.strip()
    return uuid.uuid4().hex


def log_event(
    action: str,
    *,
    result: str = "success",
    target: Optional[str] = None,
    request: Request | WebSocket | None = None,
    actor: Optional[str] = None,
    **extra,
) -> None:
    """Append one security event to the audit log (best-effort; never raises).

    `extra` may carry small non-sensitive fields (e.g. export format, count).
    Callers must NOT pass OCR text, metadata, file contents, keys or tokens.
    """
    if not settings.AUDIT_ENABLED:
        return

    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "actor": actor or (resolve_actor(request) if request is not None else ACTOR_SERVICE),
        "action": action,
        "target": target,
        "result": result,
        "request_id": request_id(request) if request is not None else None,
        "source_ip": source_ip(request) if request is not None else None,
    }
    if extra:
        record.update(extra)

    try:
        path = Path(settings.AUDIT_LOG_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False)
        with _write_lock:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        # Auditing must never break the request path; log to stderr and move on.
        logger.exception("Failed to write audit record for action=%s", action)
