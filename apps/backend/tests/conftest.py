"""Shared pytest fixtures for the security test suite.

DATA_DIR is redirected to a temp directory BEFORE the app is imported, so tests
never touch the real data/ folder. The app + settings are module-level singletons,
so this env var must be set at collection time (top of conftest), not in a fixture.
"""
import os
import tempfile

# Redirect all persistent state to a throwaway dir for the whole test session.
_TMP_DATA = tempfile.mkdtemp(prefix="indexcards_test_data_")
os.environ["DATA_DIR"] = _TMP_DATA
os.environ["TEMP_DIR"] = os.path.join(_TMP_DATA, "temp")
os.environ["BATCHES_DIR"] = os.path.join(_TMP_DATA, "batches")
os.environ["BATCHES_HISTORY_FILE"] = os.path.join(_TMP_DATA, "batches.json")
os.environ["TEMPLATES_FILE"] = os.path.join(_TMP_DATA, "templates.json")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_token(monkeypatch):
    """Enable the bearer token for a test and return it."""
    token = "test-secret-token"
    monkeypatch.setattr(settings, "AUTH_TOKEN", token)
    return token


def make_jpeg_bytes() -> bytes:
    """Minimal valid JPEG (magic bytes + EOI) for upload tests."""
    return b"\xff\xd8\xff\xe0" + b"\x00" * 16 + b"\xff\xd9"
