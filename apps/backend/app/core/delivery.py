"""HTTP lifecycle boundary: failed streams must remain incomplete on the wire."""

import logging
from typing import Optional

from fastapi import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.audit import log_event
from app.core.error_reporting import correlation_id, report_error

logger = logging.getLogger(__name__)


class DeliveryErrorBoundary:
    """Keep export/stream final frames until the downstream ASGI call succeeds.

    After headers, HTTP cannot change status or send a second error response.
    On failure we deliberately leave the body incomplete. Uvicorn closes that
    connection with a fixed diagnostic, without receiving the original exception.
    Only the final frame is held; streamed chunks are never accumulated.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        identifier = correlation_id(scope)
        started = False
        status = 500
        final: Optional[Message] = None
        completed = False
        protect_completion = True
        disconnected = False
        # Path-send bypasses application-controlled body delivery. Force the
        # standard FileResponse read/send path rather than delegate that boundary.
        scope = dict(scope)
        scope["extensions"] = {
            key: value
            for key, value in scope.get("extensions", {}).items()
            if key != "http.response.pathsend"
        }

        async def observe_receive() -> Message:
            nonlocal disconnected
            message = await receive()
            if message["type"] == "http.disconnect":
                disconnected = True
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal started, status, final, completed, protect_completion
            if message["type"] == "http.response.start":
                started = True
                status = message["status"]
                message = dict(message)
                headers = [
                    (k, v)
                    for k, v in message.get("headers", [])
                    if k.lower() != b"x-request-id"
                ]
                headers.append((b"x-request-id", identifier.encode("ascii")))
                message["headers"] = headers
                media = dict(headers).get(b"content-type", b"").split(b";", 1)[0]
                # Ordinary JSON commands must complete before BackgroundTasks
                # (notably OCR) finish. Exports/files and streams keep the guard.
                protect_completion = not (
                    media == b"application/json"
                    and b"content-length" in dict(headers)
                    and b"content-disposition" not in dict(headers)
                    and not scope["state"].get("delivery_audit")
                )
            if message["type"] == "http.response.body" and not message.get(
                "more_body", False
            ):
                if protect_completion:
                    final = message
                    return
                await send(message)
                completed = True
                return
            await send(message)

        def audit_delivery(result: str) -> None:
            event = scope["state"].get("delivery_audit")
            if event:
                log_event(
                    "bulk_run_exported",
                    result=result,
                    request=Request(scope),
                    request_id=identifier,
                    delivery_stage=(
                        "server_send_complete"
                        if result == "success"
                        else "server_send_failed"
                    ),
                    delivery_confirmation="asgi_send_only",
                    **event,
                )

        try:
            await self.app(scope, observe_receive, guarded_send)
            if not completed:
                if disconnected or final is None:
                    raise RuntimeError("incomplete_response")
                await send(final)
                completed = True
        except Exception as exc:
            report_error(
                logger,
                (
                    "http_background_failed"
                    if completed
                    else ("http_delivery_failed" if started else "http_request_failed")
                ),
                "http.deliver" if started else "http.handle",
                exc,
                scope=scope,
            )
            audit_delivery("failure")
            if not started:
                response = JSONResponse(
                    {"detail": "Internal server error"},
                    status_code=500,
                    headers={"X-Request-ID": identifier},
                )
                try:
                    await response(scope, receive, send)
                except Exception as send_exc:
                    report_error(
                        logger,
                        "http_error_response_failed",
                        "http.deliver_error",
                        send_exc,
                        scope=scope,
                    )
            # No terminal frame after response-start: do not fabricate success.
            return
        audit_delivery("success" if status < 400 else "failure")
