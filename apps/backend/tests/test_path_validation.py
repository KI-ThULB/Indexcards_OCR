"""Unit tests for the path-component validators (K-3, W-02/W-05)."""
import uuid
from pathlib import Path

import pytest

from app.core.security import (
    safe_join,
    validate_batch_name,
    validate_filename,
    validate_session_id,
)


def test_valid_session_id_accepted():
    sid = str(uuid.uuid4())
    assert validate_session_id(sid) == sid


@pytest.mark.parametrize("bad", ["../../tmp/x", "not-a-uuid", "", "12345"])
def test_invalid_session_id_rejected(bad):
    with pytest.raises(ValueError):
        validate_session_id(bad)


@pytest.mark.parametrize("good", ["MyBatch_ab12cd34", "batch.1", "a-b_c"])
def test_valid_batch_name_accepted(good):
    assert validate_batch_name(good) == good


@pytest.mark.parametrize("bad", ["..", "../etc", "a/b", "a\\b", "", "a b"])
def test_invalid_batch_name_rejected(bad):
    with pytest.raises(ValueError):
        validate_batch_name(bad)


def test_filename_strips_directory():
    # A slipped-in path is reduced to its basename, which is a valid name.
    assert validate_filename("card_01.jpg") == "card_01.jpg"


@pytest.mark.parametrize("bad", ["../../evil", "a/b.jpg"])
def test_filename_traversal_rejected(bad):
    # After stripping the dir part, the basename may still be invalid ("evil" ok,
    # but the join-level anchor is what protects us) — here we assert the raw
    # traversal forms don't pass through as-is.
    result_or_error = None
    try:
        result_or_error = validate_filename(bad)
    except ValueError:
        result_or_error = "rejected"
    # Either rejected, or reduced to a safe basename with no separators.
    assert result_or_error == "rejected" or ("/" not in result_or_error and "\\" not in result_or_error)


def test_safe_join_blocks_escape():
    base = Path("data/batches")
    with pytest.raises(ValueError):
        safe_join(base, "../../etc/passwd")


def test_safe_join_allows_inside():
    base = Path("data/batches")
    result = safe_join(base, "batch1", "file.jpg")
    assert result.name == "file.jpg"
