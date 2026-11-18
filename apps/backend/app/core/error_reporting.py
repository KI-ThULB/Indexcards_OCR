"""Content-free diagnostics for SAR-02 error boundaries."""

import logging
import uuid
from typing import Optional

from starlette.types import Scope


def correlation_id(scope: Optional[Scope] = None) -> str:
    # Never echo an untrusted request header into logs or response headers.
    if scope is None:
        return uuid.uuid4().hex
    state = scope.setdefault("state", {})
    if "error_correlation_id" not in state:
        state["error_correlation_id"] = uuid.uuid4().hex
    return str(state["error_correlation_id"])


def report_error(
    logger: logging.Logger,
    code: str,
    operation: str,
    exc: Exception,
    *,
    scope: Optional[Scope] = None,
    event_id: Optional[str] = None,
) -> str:
    """Callers supply fixed codes/operations, never exception-derived text."""
    identifier = event_id or correlation_id(scope)
    logger.error(
        "code=%s operation=%s correlation_id=%s exception_type=%s",
        code,
        operation,
        identifier,
        type(exc).__name__,
    )
    return identifier
