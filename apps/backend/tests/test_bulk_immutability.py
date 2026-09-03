"""The source files under BULK_IMPORT_ROOT are immutable.

A hardlink shares its inode with the archival original, so any in-place write to
a batch-side image would silently corrupt the source scan. These tests record
SHA-256 + size + mtime for every source file before a run and assert byte
identity afterwards, for every downstream operation the pipeline performs:
successful processing, failure handling (move to ``_errors/``), retry (both
endpoints), and cleanup/purge/delete. The source directory *listing* must also
be unchanged — nothing added, removed or renamed — and ``copy`` mode must behave
identically.

All VLM calls are mocked; no network.
"""
import asyncio
import hashlib
import os
from pathlib import Path

import pytest

from app.api.api_v1.endpoints import batches as batches_ep
from app.core.config import settings
from app.services import bulk_import
from app.services.batch_manager import batch_manager
from app.services.ocr_engine import ocr_engine

JPEG_A = b"\xff\xd8\xff\xe0" + b"AAAA" * 8 + b"\xff\xd9"
JPEG_B = b"\xff\xd8\xff\xe0" + b"BBBB" * 8 + b"\xff\xd9"


# --------------------------------------------------------------------------- #
# Fingerprinting helpers
# --------------------------------------------------------------------------- #
def _fingerprint(root: Path) -> dict:
    """SHA-256 + size + mtime_ns for every file under *root*, keyed by rel path."""
    out = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            st = path.stat()
            out[str(path.relative_to(root))] = (
                hashlib.sha256(path.read_bytes()).hexdigest(),
                st.st_size,
                st.st_mtime_ns,
            )
    return out


def _assert_sources_untouched(root: Path, before: dict, what: str) -> None:
    after = _fingerprint(root)
    assert set(after) == set(before), f"source listing changed after {what}"
    for rel, fp in before.items():
        assert after[rel] == fp, f"source file {rel} was modified after {what}"


@pytest.fixture(autouse=True)
def _no_leaked_batches():
    """Delete any batch this module creates.

    Bulk tests drive real batches through run_ocr_task, which stamps
    completed_at in batches.json. Leaving those behind would leak into other
    modules' global-state assertions (e.g. the retention preview), so each test
    cleans up after itself.
    """
    before = set(batch_manager.list_batches())
    yield
    for name in set(batch_manager.list_batches()) - before:
        try:
            batch_manager.release_batch_lock(name)
            batch_manager.delete_batch(name)
        except Exception:
            pass


@pytest.fixture
def import_root(tmp_path, monkeypatch):
    """Three folders x two mixed-case JPGs — the documented smoke-test shape."""
    root = tmp_path / "amiga"
    for i in range(1, 4):
        folder = root / f"Batch_{i:03d}"
        folder.mkdir(parents=True)
        (folder / f"IMG_{i}_a.JPG").write_bytes(JPEG_A)
        (folder / f"IMG_{i}_b.jpeg").write_bytes(JPEG_B)
    monkeypatch.setattr(settings, "BULK_IMPORT_ROOT", str(root))
    return root


@pytest.fixture
def mock_vlm(monkeypatch):
    monkeypatch.setattr(
        ocr_engine,
        "_call_vlm_api_resilient",
        lambda *a, **k: ({"fields": {"Komponist": "Bach"}, "confidence_overall": 0.9}, None),
    )


@pytest.fixture
def failing_vlm(monkeypatch):
    monkeypatch.setattr(
        ocr_engine, "_call_vlm_api_resilient", lambda *a, **k: (None, "HTTP 500: upstream")
    )


def _import(folder="Batch_001", mode=None) -> str:
    return bulk_import.materialise_folder(
        folder, fields=["Komponist"], mode=mode
    )["batch_name"]


def _process(batch_name: str):
    return asyncio.run(
        ocr_engine.process_batch(
            batch_dir=batch_manager.get_batch_path(batch_name),
            fields=["Komponist"],
            api_key="k",
        )
    )


# --------------------------------------------------------------------------- #
# Import itself
# --------------------------------------------------------------------------- #
def test_import_uses_hardlinks_by_default(import_root):
    before = _fingerprint(import_root)
    batch = _import()

    src = import_root / "Batch_001" / "IMG_1_a.JPG"
    dst = batch_manager.get_batch_path(batch) / "IMG_1_a.JPG"
    assert dst.exists()
    assert os.stat(src).st_ino == os.stat(dst).st_ino, "expected a hardlink (same inode)"
    _assert_sources_untouched(import_root, before, "import")


def test_import_preserves_mixed_case_filenames(import_root):
    batch = _import()
    names = {p.name for p in bulk_import.source_images(batch_manager.get_batch_path(batch))}
    assert names == {"IMG_1_a.JPG", "IMG_1_b.jpeg"}


def test_copy_mode_does_not_share_inode_and_leaves_sources_alone(import_root):
    before = _fingerprint(import_root)
    batch = _import(mode="copy")

    src = import_root / "Batch_001" / "IMG_1_a.JPG"
    dst = batch_manager.get_batch_path(batch) / "IMG_1_a.JPG"
    assert dst.read_bytes() == src.read_bytes()
    assert os.stat(src).st_ino != os.stat(dst).st_ino
    _assert_sources_untouched(import_root, before, "copy-mode import")


# --------------------------------------------------------------------------- #
# 1. after SUCCESSFUL processing
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("mode", ["hardlink", "copy"])
def test_sources_untouched_after_successful_processing(import_root, mock_vlm, mode):
    before = _fingerprint(import_root)
    batch = _import(mode=mode)
    results = _process(batch)

    assert len(results) == 2 and all(r["success"] for r in results)
    _assert_sources_untouched(import_root, before, f"successful processing ({mode})")


# --------------------------------------------------------------------------- #
# 2. after FAILED processing (images moved to _errors/)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("mode", ["hardlink", "copy"])
def test_sources_untouched_after_failed_processing(import_root, failing_vlm, mode):
    before = _fingerprint(import_root)
    batch = _import(mode=mode)
    results = _process(batch)

    assert all(r["success"] is False for r in results)
    # Failed cards were moved into _errors/ — a move of the batch-side link only.
    error_dir = batch_manager.get_batch_path(batch) / "_errors"
    assert {p.name for p in error_dir.iterdir()} == {"IMG_1_a.JPG", "IMG_1_b.jpeg"}
    _assert_sources_untouched(import_root, before, f"failed processing ({mode})")


# --------------------------------------------------------------------------- #
# 3. after RETRY — both endpoints
# --------------------------------------------------------------------------- #
def test_sources_untouched_after_retry_image_endpoint(import_root, client, monkeypatch):
    before = _fingerprint(import_root)
    batch = _import()

    monkeypatch.setattr(
        ocr_engine, "_call_vlm_api_resilient", lambda *a, **k: (None, "HTTP 500: upstream")
    )
    _process(batch)

    monkeypatch.setattr(
        ocr_engine, "_call_vlm_api_resilient", lambda *a, **k: ({"Komponist": "Bach"}, None)
    )
    resp = client.post(f"/api/v1/batches/{batch}/retry-image/IMG_1_a.JPG")
    assert resp.status_code == 200, resp.text

    _assert_sources_untouched(import_root, before, "retry-image")


def test_sources_untouched_after_retry_batch_endpoint(import_root, client, monkeypatch):
    before = _fingerprint(import_root)
    batch = _import()

    monkeypatch.setattr(
        ocr_engine, "_call_vlm_api_resilient", lambda *a, **k: (None, "HTTP 500: upstream")
    )
    _process(batch)

    monkeypatch.setattr(
        ocr_engine, "_call_vlm_api_resilient", lambda *a, **k: ({"Komponist": "Bach"}, None)
    )
    resp = client.post(f"/api/v1/batches/{batch}/retry")
    assert resp.status_code == 200, resp.text

    _assert_sources_untouched(import_root, before, "retry-batch")


# --------------------------------------------------------------------------- #
# 4. after CLEANUP / PURGE / DELETE
# --------------------------------------------------------------------------- #
def test_sources_survive_purge_batch_data(import_root, mock_vlm):
    before = _fingerprint(import_root)
    batch = _import()
    _process(batch)

    assert batch_manager.purge_batch_data(batch) is True
    assert not batch_manager.get_batch_path(batch).exists()
    _assert_sources_untouched(import_root, before, "purge_batch_data")


def test_sources_survive_delete_batch(import_root, mock_vlm):
    before = _fingerprint(import_root)
    batch = _import()
    _process(batch)

    assert batch_manager.delete_batch(batch) is True
    assert not batch_manager.get_batch_path(batch).exists()
    _assert_sources_untouched(import_root, before, "delete_batch")


def test_sources_survive_delete_of_all_generated_batches(import_root, mock_vlm):
    """The whole generated run can be thrown away without touching the archive."""
    before = _fingerprint(import_root)
    batches = [_import(f"Batch_{i:03d}") for i in range(1, 4)]
    for b in batches:
        _process(b)
    for b in batches:
        batch_manager.delete_batch(b)

    _assert_sources_untouched(import_root, before, "deleting every generated batch")


# --------------------------------------------------------------------------- #
# 5. the pipeline never opens an image for writing
# --------------------------------------------------------------------------- #
def test_resize_is_in_memory_only(import_root):
    """_encode_image_to_base64 must resize into a buffer, never over the file.
    A hardlink means an in-place save would corrupt the archival original."""
    before = _fingerprint(import_root)
    batch = _import()
    img = batch_manager.get_batch_path(batch) / "IMG_1_a.JPG"

    ocr_engine._encode_image_to_base64(img, max_size=8)

    _assert_sources_untouched(import_root, before, "base64 encode + resize")


def test_serving_a_batch_image_is_read_only(import_root, client):
    before = _fingerprint(import_root)
    batch = _import()

    resp = client.get(f"/batches-static/{batch}/IMG_1_a.JPG")
    assert resp.status_code == 200
    assert resp.content == JPEG_A

    _assert_sources_untouched(import_root, before, "serving the image")


def test_no_write_mode_open_against_batches_dir(import_root, mock_vlm, monkeypatch):
    """Belt and braces: fail loudly if anything in the pipeline opens a file
    under BATCHES_DIR in a writing mode other than the JSON sidecars."""
    real_open = os.open
    batches_dir = Path(settings.BATCHES_DIR).resolve()
    offenders: list = []

    write_flags = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_TRUNC | os.O_CREAT

    def guarded_open(path, flags, *a, **k):
        try:
            resolved = Path(os.fsdecode(path)).resolve()
            if (
                flags & write_flags
                and batches_dir in resolved.parents
                and bulk_import.is_supported_image(resolved)
            ):
                offenders.append(str(resolved))
        except (ValueError, OSError):
            pass
        return real_open(path, flags, *a, **k)

    monkeypatch.setattr(os, "open", guarded_open)
    batch = _import()
    _process(batch)
    monkeypatch.undo()

    assert offenders == [], f"image files opened for writing: {offenders}"


# --------------------------------------------------------------------------- #
# 6. source directory listing is unchanged
# --------------------------------------------------------------------------- #
def test_source_listing_unchanged_end_to_end(import_root, mock_vlm):
    before_names = sorted(str(p.relative_to(import_root)) for p in import_root.rglob("*"))
    for i in range(1, 4):
        batch = _import(f"Batch_{i:03d}")
        _process(batch)
    after_names = sorted(str(p.relative_to(import_root)) for p in import_root.rglob("*"))
    assert after_names == before_names


def test_import_does_not_leave_temp_sessions_behind(import_root, mock_vlm):
    _import()
    temp_dir = Path(settings.TEMP_DIR)
    leftovers = [p for p in temp_dir.iterdir()] if temp_dir.exists() else []
    assert leftovers == []


def test_failed_import_cleans_up_and_leaves_sources_alone(import_root, monkeypatch):
    before = _fingerprint(import_root)

    def boom(*a, **k):
        raise RuntimeError("simulated failure during batch creation")

    monkeypatch.setattr(batch_manager, "create_batch", boom)
    with pytest.raises(RuntimeError):
        _import()

    _assert_sources_untouched(import_root, before, "a failed import")
    temp_dir = Path(settings.TEMP_DIR)
    assert [p for p in temp_dir.iterdir()] == [] if temp_dir.exists() else True


def test_batches_endpoint_module_reuses_shared_checkpoint(import_root):
    """Guard against a second checkpoint implementation reappearing."""
    from app.core import checkpoint as shared

    assert batches_ep.read_checkpoint is shared.read_checkpoint
    assert batches_ep.write_checkpoint is shared.write_checkpoint
