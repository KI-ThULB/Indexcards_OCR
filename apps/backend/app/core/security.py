"""Central security primitives for the backend (pentest remediation K-3, W-01, H-4).

Two concerns live here so they can be reused everywhere and unit-tested in isolation:

  1. Path-component validation — reject `../` traversal and stray separators in any
     user-controlled path part (session_id, batch_name, template_id, filename) BEFORE
     it reaches a filesystem operation. Validation is applied at the service/endpoint
     boundary, not the route, per the pentest report's guidance (W-09).
  2. Authentication — an optional bearer token on the JSON API, and an Origin+token
     check for the WebSocket handshake. Both are no-ops when AUTH_TOKEN is unset, so
     local single-curator dev is unaffected.
"""
import re
import secrets
from pathlib import Path
from typing import Optional

from fastapi import Header, HTTPException, WebSocket, status

from app.core.config import settings

# A generated session id is a uuid4 str; accept only that shape.
_SESSION_ID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
# batch_name / template_id / filename: safe chars only, no separators, no dotfiles.
_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _reject(detail: str) -> None:
    raise ValueError(detail)


def validate_session_id(session_id: str) -> str:
    """Return session_id unchanged if it is a valid uuid4, else raise ValueError."""
    if not session_id or not _SESSION_ID_RE.match(session_id):
        _reject(f"Invalid session id: {session_id!r}")
    return session_id


def _validate_name(value: str, kind: str) -> str:
    """Shared validator for batch_name / template_id / filename path components."""
    if not value or value in (".", "..") or not _NAME_RE.match(value):
        _reject(f"Invalid {kind}: {value!r}")
    return value


def validate_batch_name(batch_name: str) -> str:
    return _validate_name(batch_name, "batch name")


def validate_template_id(template_id: str) -> str:
    return _validate_name(template_id, "template id")


def validate_filename(filename: str) -> str:
    """Validate a single filename. Strips any directory part first (defense in depth)."""
    bare = Path(filename).name  # drop any path components an attacker slipped in
    return _validate_name(bare, "filename")


def safe_join(base: Path, *parts: str) -> Path:
    """Join user-controlled parts onto base and assert the result stays inside base.

    Raises ValueError if the resolved path escapes base (traversal). This is the
    last-line anchor: even if a caller forgets a validator, the resolved-path check
    prevents writing/reading outside the intended directory (W-02/W-05).
    """
    base_resolved = base.resolve()
    candidate = base_resolved.joinpath(*parts).resolve()
    if candidate != base_resolved and base_resolved not in candidate.parents:
        _reject(f"Path escapes base directory: {candidate}")
    return candidate


# --------------------------------------------------------------------------- #
# Authentication
# --------------------------------------------------------------------------- #
def _token_matches(candidate: Optional[str]) -> bool:
    """Constant-time comparison against the configured AUTH_TOKEN."""
    if not candidate:
        return False
    return secrets.compare_digest(candidate, settings.AUTH_TOKEN)


async def require_auth(authorization: Optional[str] = Header(default=None)) -> None:
    """FastAPI dependency guarding the JSON API (W-01).

    No-op when AUTH_TOKEN is unset (local dev). When set, requires a matching
    `Authorization: Bearer <token>` header; otherwise 401.
    """
    if not settings.AUTH_TOKEN:
        return
    scheme, _, credential = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not _token_matches(credential):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def check_ws_auth(websocket: WebSocket) -> bool:
    """Validate a WebSocket handshake before accept() (W-04/H-4).

    Rejects a cross-site Origin (when an allow-list is configured) and, if
    AUTH_TOKEN is set, requires a matching `?token=` query parameter. Returns
    True if the handshake may proceed.
    """
    allowed = settings.allowed_ws_origins
    origin = websocket.headers.get("origin")
    # Only enforce the Origin check when an allow-list is configured. A missing
    # Origin (non-browser client) is allowed through the origin gate; the token
    # gate below still applies when a token is configured.
    if allowed and origin is not None and origin not in allowed:
        return False
    if settings.AUTH_TOKEN and not _token_matches(websocket.query_params.get("token")):
        return False
    return True
