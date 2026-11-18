"""Single-process session primitives. Transport and authorization belong to B2."""

import hashlib
import re
import secrets
import threading
import time
from collections.abc import Callable

from argon2 import PasswordHasher, Type, extract_parameters
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from pydantic import SecretStr

_HASHER = PasswordHasher()
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}")
MIN_TTL_SECONDS = 1
MAX_TTL_SECONDS = 86_400
MAX_CAPACITY = 4096


class OperatorPassword:
    def __init__(self, encoded_hash: SecretStr) -> None:
        value = encoded_hash.get_secret_value()
        if len(value) > 512:
            raise ValueError("Invalid operator password hash")
        try:
            params = extract_parameters(value)
            if (
                params.type is not Type.ID or params.version != 19
                or not 19 * 1024 <= params.memory_cost <= 256 * 1024
                or not 2 <= params.time_cost <= 6
                or not 1 <= params.parallelism <= 4
                or not 16 <= params.salt_len <= 64
                or not 32 <= params.hash_len <= 64
            ):
                raise ValueError("Invalid Argon2id parameters")
            # Verify once with an unrelated fixed input to validate the encoding.
            try:
                _HASHER.verify(value, "configuration validation probe")
            except VerifyMismatchError:
                pass
        except (InvalidHashError, VerificationError, ValueError, OverflowError):
            raise ValueError("Invalid operator password hash") from None
        self._hash = encoded_hash

    def verify(self, password: str) -> bool:
        if not password or len(password) > 1024:
            return False
        try:
            return _HASHER.verify(self._hash.get_secret_value(), password)
        except (InvalidHashError, VerificationError, UnicodeError):
            return False


class SessionCapacityError(RuntimeError):
    pass


class SessionStore:
    def __init__(
        self, *, ttl_seconds: int, capacity: int, clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not MIN_TTL_SECONDS <= ttl_seconds <= MAX_TTL_SECONDS or not 1 <= capacity <= MAX_CAPACITY:
            raise ValueError("Invalid session limits")
        self._ttl_seconds = ttl_seconds
        self._capacity = capacity
        self._clock = clock
        self._expires_at: dict[bytes, float] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _digest(token: str) -> bytes | None:
        if not _TOKEN_PATTERN.fullmatch(token):
            return None
        return hashlib.sha256(token.encode("ascii")).digest()

    def create(self) -> str:
        with self._lock:
            now = self._clock()
            self._expires_at = {key: end for key, end in self._expires_at.items() if end > now}
            if len(self._expires_at) >= self._capacity:
                raise SessionCapacityError("Session capacity reached")
            while True:
                token = secrets.token_urlsafe(32)
                digest = hashlib.sha256(token.encode("ascii")).digest()
                if digest not in self._expires_at:
                    self._expires_at[digest] = now + self._ttl_seconds
                    return token

    def is_active(self, token: str) -> bool:
        digest = self._digest(token)
        if digest is None:
            return False
        with self._lock:
            expires = self._expires_at.get(digest)
            if expires is None:
                return False
            if self._clock() >= expires:
                del self._expires_at[digest]
                return False
            return True

    def revoke(self, token: str) -> bool:
        digest = self._digest(token)
        if digest is None:
            return False
        with self._lock:
            expires = self._expires_at.pop(digest, None)
            return expires is not None and expires > self._clock()
