"""Regression tests: image extension matching is case-insensitive.

A downstream user on Ubuntu/WSL uploaded ``IMG_6662.JPG`` (uppercase suffix);
upload succeeded but processing reported "No images found" because the batch
glob was case-sensitive. These tests lock in case-insensitive detection at both
the shared helper level and end-to-end through upload + enumeration, while
confirming unsupported extensions are still rejected.
"""
import pytest
from conftest import make_jpeg_bytes, make_tiff_bytes

from app.core.images import is_supported_image, iter_image_files


# --------------------------------------------------------------------------- #
# Unit: the shared helper normalises case before comparison
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "name",
    [
        "image.jpg", "image.JPG", "image.JpG",
        "image.jpeg", "image.JPEG",
        "image.png", "image.PNG",
        "scan.tif", "scan.TIF", "scan.TiF",
        "scan.tiff", "scan.TIFF",
    ],
)
def test_is_supported_image_accepts_any_case(name):
    assert is_supported_image(name) is True


@pytest.mark.parametrize(
    "name",
    ["notes.txt", "archive.zip", "page.pdf", "image.gif", "noext", "trailing.jpg.exe"],
)
def test_is_supported_image_rejects_unsupported(name):
    assert is_supported_image(name) is False


def test_iter_image_files_matches_mixed_case_and_skips_others(tmp_path):
    # Supported, various cases
    for n in ["a.jpg", "b.JPG", "c.JpG", "d.TIFF", "e.TiF", "f.png"]:
        (tmp_path / n).write_bytes(b"x")
    # Not images / not files
    (tmp_path / "checkpoint.json").write_bytes(b"{}")
    (tmp_path / "notes.txt").write_bytes(b"x")
    (tmp_path / "_errors").mkdir()

    found = {p.name for p in iter_image_files(tmp_path)}
    assert found == {"a.jpg", "b.JPG", "c.JpG", "d.TIFF", "e.TiF", "f.png"}


# --------------------------------------------------------------------------- #
# End-to-end: upload accepts uppercase/mixed-case extensions and preserves the
# original filename exactly (no renaming to lowercase).
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "filename,payload",
    [
        ("image.JPG", make_jpeg_bytes()),
        ("image.JpG", make_jpeg_bytes()),
        ("scan.TIFF", make_tiff_bytes()),
        ("scan.TiF", make_tiff_bytes()),
    ],
)
def test_upload_accepts_uppercase_extension_and_preserves_name(client, filename, payload):
    files = {"files": (filename, payload, "application/octet-stream")}
    r = client.post("/api/v1/upload/", files=files)
    assert r.status_code == 200, r.text
    # Original casing preserved — file is NOT renamed to lowercase.
    assert r.json()["filenames"] == [filename]


def test_upload_still_rejects_unsupported_extension(client):
    files = {"files": ("evil.exe", make_jpeg_bytes(), "application/octet-stream")}
    r = client.post("/api/v1/upload/", files=files)
    assert r.status_code == 400
