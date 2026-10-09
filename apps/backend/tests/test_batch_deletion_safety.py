"""Regression tests for safe deletion of OCR batches."""

import json
import multiprocessing
import time
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services.batch_manager import BatchManager


@pytest.fixture
def manager(tmp_path, monkeypatch):
    batches_dir = tmp_path / "batches"
    history_file = tmp_path / "batches.json"

    monkeypatch.setattr(settings, "BATCHES_DIR", str(batches_dir))
    monkeypatch.setattr(settings, "BATCHES_HISTORY_FILE", str(history_file))
    monkeypatch.setattr(settings, "TEMP_DIR", str(tmp_path / "temp"))

    manager = BatchManager(data_dir=str(tmp_path))
    return manager


def create_test_batch(manager, name="Test_Batch"):
    batch_path = manager.batches_dir / name
    batch_path.mkdir()
    (batch_path / "image.jpg").write_bytes(b"test image")
    return batch_path


def test_active_batch_cannot_be_deleted(manager):
    batch_path = create_test_batch(manager)

    assert manager.acquire_batch_lock("Test_Batch") is True

    try:
        with pytest.raises(RuntimeError, match="cannot be deleted"):
            manager.delete_batch("Test_Batch")

        assert batch_path.exists()
        assert (batch_path / "image.jpg").exists()
        assert (batch_path / ".run.lock").exists()
    finally:
        manager.release_batch_lock("Test_Batch")


def test_inactive_batch_can_be_deleted(manager):
    batch_path = create_test_batch(manager)

    assert manager.delete_batch("Test_Batch") is True
    assert not batch_path.exists()


def test_missing_batch_returns_false(manager):
    assert manager.delete_batch("Nonexistent_Batch") is False

def test_api_rejects_deletion_of_active_batch(manager, monkeypatch):
    from app.api.api_v1.endpoints import batches as batches_endpoint

    monkeypatch.setattr(batches_endpoint, "batch_manager", manager)

    batch_path = create_test_batch(manager)
    assert manager.acquire_batch_lock("Test_Batch") is True

    try:
        with TestClient(app) as client:
            response = client.delete("/api/v1/batches/Test_Batch")

        assert response.status_code == 409
        assert "cannot be deleted" in response.json()["detail"]
        assert batch_path.exists()
        assert (batch_path / "image.jpg").exists()
        assert (batch_path / ".run.lock").exists()
    finally:
        manager.release_batch_lock("Test_Batch")

def test_active_batch_cannot_be_purged(manager):
    batch_path = create_test_batch(manager)

    assert manager.acquire_batch_lock("Test_Batch") is True

    try:
        with pytest.raises(RuntimeError, match="a run is active"):
            manager.purge_batch_data("Test_Batch")

        assert batch_path.exists()
        assert (batch_path / "image.jpg").exists()
        assert (batch_path / ".run.lock").exists()
    finally:
        manager.release_batch_lock("Test_Batch")

def _hold_operations_lock(lock_path, ready, release):
    """Hold the coordination lock in a separate process."""
    import fcntl

    with open(lock_path, "a+b") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        ready.set()
        release.wait(timeout=10)
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def test_batch_lock_waits_for_other_process(manager):
    """OCR lock acquisition must wait for another process's coordination lock."""
    batch_path = create_test_batch(manager)
    lock_path = manager.batches_dir / ".batch-operations.lock"

    ctx = multiprocessing.get_context("spawn")
    ready = ctx.Event()
    release = ctx.Event()

    process = ctx.Process(
        target=_hold_operations_lock,
        args=(str(lock_path), ready, release),
    )
    process.start()

    try:
        assert ready.wait(timeout=5), "Child process did not acquire lock"

        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(manager.acquire_batch_lock, "Test_Batch")

            time.sleep(0.2)
            assert not future.done(), (
                "OCR start bypassed the coordination lock"
            )

            release.set()
            assert future.result(timeout=5) is True

        assert (batch_path / ".run.lock").exists()
    finally:
        release.set()
        process.join(timeout=5)
        if process.is_alive():
            process.terminate()
            process.join()
        manager.release_batch_lock("Test_Batch")

def test_ocr_cannot_start_during_batch_deletion(manager, monkeypatch):
    """An OCR start cannot recreate a lock while deletion is in progress."""
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from app.services.batch_manager import BatchMissingError

    batch_path = create_test_batch(manager)

    deletion_started = threading.Event()
    allow_deletion = threading.Event()

    import app.services.batch_manager as batch_module

    original_rmtree = batch_module.shutil.rmtree

    def slow_rmtree(path, *args, **kwargs):
        if str(path) == str(batch_path):
            deletion_started.set()
            assert allow_deletion.wait(timeout=5)
        return original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(batch_module.shutil, "rmtree", slow_rmtree)

    with ThreadPoolExecutor(max_workers=2) as executor:
        delete_future = executor.submit(manager.delete_batch, "Test_Batch")

        try:
            assert deletion_started.wait(timeout=5)

            start_future = executor.submit(
                manager.acquire_batch_lock, "Test_Batch"
            )

            # OCR must not acquire its run lock during deletion.
            import time
            time.sleep(0.2)
            assert not start_future.done()

        finally:
            allow_deletion.set()

        assert delete_future.result(timeout=5) is True

        with pytest.raises(BatchMissingError):
            start_future.result(timeout=5)

    assert not batch_path.exists()
