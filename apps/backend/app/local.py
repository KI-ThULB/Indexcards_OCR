"""Loopback-only development entry point used by npm run dev."""
import argparse
import os

import uvicorn
from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import settings

HOST = "127.0.0.1"
API_PORT = int(os.environ.get("INDEXCARDS_API_PORT", "8000"))
DEV_PORT = int(os.environ.get("INDEXCARDS_DEV_PORT", "5173"))
LOCAL_HOSTS = {f"{host}:{port}" for host in (HOST, "localhost") for port in (API_PORT, DEV_PORT)}
LOCAL_ORIGINS = {f"http://{host}" for host in LOCAL_HOSTS}


class LocalAccess:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        peer = scope.get("client")
        hosts = headers.getlist("host")
        origins = headers.getlist("origin")
        if (
            not peer
            or peer[0] != HOST
            or len(hosts) != 1
            or hosts[0] not in LOCAL_HOSTS
            or len(origins) > 1
            or (origins and origins[0] not in LOCAL_ORIGINS)
        ):
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            else:
                await PlainTextResponse("Local access only", status_code=403)(scope, receive, send)
            return
        await self.app({**scope, "indexcards.local": True}, receive, send)


def create_local_app() -> ASGIApp:
    from app._application import _create_application

    return _create_application(LocalAccess)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    if settings.HOST != HOST:
        parser.error("Local startup requires HOST=127.0.0.1")
    if API_PORT == DEV_PORT or not all(1 <= port <= 65535 for port in (API_PORT, DEV_PORT)):
        parser.error("Local API and frontend ports must be distinct and between 1 and 65535")
    uvicorn.run(
        "app.local:create_local_app", factory=True, host=HOST, port=API_PORT,
        reload=True, workers=1, proxy_headers=False,
    )


if __name__ == "__main__":
    main()
