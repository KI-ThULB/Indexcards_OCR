"""Shared slowapi limiter (pentest remediation W-06/H-2).

A single Limiter instance is imported by main.py (to register the handler) and by
the endpoint modules (to decorate expensive routes). Storage is configurable via
RATE_LIMIT_STORAGE_URI — use redis://… when running multiple uvicorn workers so
limits are shared across processes rather than per-process.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.RATE_LIMIT_STORAGE_URI,
    # Limits are opt-in per route via @limiter.limit(...); no global default.
)
