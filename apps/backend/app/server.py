"""Reserved server ASGI entrypoint. All network requests are refused in B1."""

import ipaddress
import re
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict
from starlette.responses import PlainTextResponse
from starlette.types import Receive, Scope, Send

from app.core.config import default_env_file
from app.core.sessions import MAX_CAPACITY, MAX_TTL_SECONDS, MIN_TTL_SECONDS, OperatorPassword, SessionStore

_DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")


def validate_public_origin(origin: str) -> None:
    try:
        parsed = urlsplit(origin)
        host = parsed.hostname
        port = parsed.port
        if parsed.scheme != "https" or not host:
            raise ValueError
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            labels = host.split(".")
            if (
                len(host) > 253 or not labels[-1][0:1].isalpha()
                or not all(_DNS_LABEL.fullmatch(label) for label in labels)
            ):
                raise ValueError from None
            authority = host
        else:
            authority = f"[{address}]" if address.version == 6 else str(address)
        if port is not None:
            if not 1 <= port <= 65535 or port == 443:
                raise ValueError
            authority += f":{port}"
        if origin != f"https://{authority}" or "%" in authority:
            raise ValueError
    except ValueError:
        raise ValueError("SERVER_PUBLIC_ORIGIN must be one canonical HTTPS origin without a path or credentials") from None


class ServerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file_encoding="utf-8", case_sensitive=True, extra="ignore", hide_input_in_errors=True,
    )

    SERVER_PUBLIC_ORIGIN: str
    SERVER_OPERATOR_PASSWORD_HASH: SecretStr
    SERVER_SESSION_TTL_SECONDS: int = Field(default=3600, ge=MIN_TTL_SECONDS, le=MAX_TTL_SECONDS)
    SERVER_SESSION_CAPACITY: int = Field(default=128, ge=1, le=MAX_CAPACITY)

    def build_authentication(self) -> tuple[OperatorPassword, SessionStore]:
        validate_public_origin(self.SERVER_PUBLIC_ORIGIN)
        return (
            OperatorPassword(self.SERVER_OPERATOR_PASSWORD_HASH),
            SessionStore(ttl_seconds=self.SERVER_SESSION_TTL_SECONDS, capacity=self.SERVER_SESSION_CAPACITY),
        )


_DISABLED = "Server profile disabled until Phase B2 provides complete route protection"


async def app(scope: Scope, receive: Receive, send: Send) -> None:
    if scope["type"] == "lifespan":
        await receive()
        try:
            # pydantic-settings accepts this source override at runtime.
            settings = ServerSettings(_env_file=default_env_file())  # type: ignore[call-arg]
            settings.build_authentication()
        except (ValueError, ValidationError):
            message = (
                "Invalid server configuration. Check SERVER_PUBLIC_ORIGIN, "
                "SERVER_OPERATOR_PASSWORD_HASH and session limits."
            )
        else:
            message = _DISABLED
        await send({"type": "lifespan.startup.failed", "message": message})
    elif scope["type"] == "http":
        await PlainTextResponse(_DISABLED, status_code=503)(scope, receive, send)
    elif scope["type"] == "websocket":
        await send({"type": "websocket.close", "code": 1008})
