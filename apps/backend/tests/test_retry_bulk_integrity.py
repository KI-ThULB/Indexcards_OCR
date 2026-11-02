"""SAR-03b: preflight retries and never export/count unavailable data as empty."""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from app.api.api_v1.endpoints import batches
from app.core import atomic_io
from app.core.checkpoint import CheckpointError, read_checkpoint, write_checkpoint
from app.core.config import settings
from app.services import bulk_export, bulk_orchestrator
from app.services.batch_manager import batch_manager
from app.services.bulk_manager import bulk_manager
from test_error_disclosure import SECRET, assert_safe, make_run
from test_error_disclosure import isolated_state as isolated_state


def row(name="done.jpg", success=True):
    return {
        "filename": name,
        "success": success,
        "duration": 0,
        "data": {"value": "keep"},
    }


def fail(*args, **kwargs):
    raise PermissionError(SECRET)


@pytest.fixture
def retry(monkeypatch):
    path = batch_manager.batches_dir / "retry"
    (path / "_errors").mkdir(parents=True)
    (path / "_errors" / "bad.jpg").write_bytes(b"original-image")
    write_checkpoint(
        path / "checkpoint.json", [row(), row("bad.jpg", False)], [{"id": "keep"}]
    )
    job = AsyncMock()
    monkeypatch.setattr(batches, "run_ocr_task", job)
    return path, job


@pytest.mark.parametrize("endpoint", ["retry-image/bad.jpg", "retry"])
@pytest.mark.parametrize("fault", ["corrupt", "unreadable"])
def test_retry_rejects_bad_checkpoint_before_move(
    client, retry, monkeypatch, caplog, endpoint, fault
):
    path, job = retry
    checkpoint = path / "checkpoint.json"
    if fault == "corrupt":
        checkpoint.write_text('{"' + SECRET)
    else:
        monkeypatch.setattr(batches, "read_checkpoint", fail)
    original, stamp = checkpoint.read_bytes(), checkpoint.stat().st_mtime_ns
    response = client.post(f"/api/v1/batches/retry/{endpoint}")
    assert response.status_code == 500
    job.assert_not_called()
    assert (path / "_errors" / "bad.jpg").read_bytes() == b"original-image"
    assert not (path / "bad.jpg").exists()
    assert (
        checkpoint.read_bytes() == original and checkpoint.stat().st_mtime_ns == stamp
    )
    assert not batch_manager.is_run_active("retry")
    assert_safe(caplog, response.text)


@pytest.mark.parametrize("stage", ["write", "fsync", "replace"])
def test_retry_write_failure_rolls_back_image(
    client, retry, monkeypatch, caplog, stage
):
    path, job = retry
    checkpoint = path / "checkpoint.json"
    original, stamp = checkpoint.read_bytes(), checkpoint.stat().st_mtime_ns
    begin = batch_manager.begin_retry_preparation
    checkpoint_attempted = []

    def prepare(*args, **kwargs):
        begin(*args, **kwargs)
        # Inject after the write-ahead marker saves: exercise checkpoint writes.
        def broken(*args, **kwargs):
            checkpoint_attempted.append(True)
            return fail()
        if stage == "write":
            monkeypatch.setattr(atomic_io, "atomic_write_text", broken)
        else:
            monkeypatch.setattr(atomic_io.os, stage, broken)

    monkeypatch.setattr(batch_manager, "begin_retry_preparation", prepare)
    response = client.post("/api/v1/batches/retry/retry-image/bad.jpg")
    assert checkpoint_attempted
    assert response.status_code == 500
    job.assert_not_called()
    assert (
        checkpoint.read_bytes() == original and checkpoint.stat().st_mtime_ns == stamp
    )
    assert (path / "_errors" / "bad.jpg").read_bytes() == b"original-image"
    assert not (path / "bad.jpg").exists()
    assert not batch_manager.is_run_active("retry")
    assert_safe(caplog, response.text)


def test_rollback_failure_keeps_lock_for_manual_recovery(
    client, retry, monkeypatch, caplog
):
    path, job = retry
    original = (path / "checkpoint.json").read_bytes()
    real_rename = Path.rename

    def rename(source, destination):
        if source.parent == path:
            raise OSError(SECRET)
        return real_rename(source, destination)

    monkeypatch.setattr(Path, "rename", rename)
    monkeypatch.setattr(batches, "write_checkpoint", fail)
    response = client.post("/api/v1/batches/retry/retry-image/bad.jpg")
    assert response.status_code == 500 and "remains locked" in response.text
    job.assert_not_called()
    assert batch_manager.is_run_active("retry")
    assert (path / "bad.jpg").read_bytes() == b"original-image"
    assert (path / "checkpoint.json").read_bytes() == original
    assert client.post("/api/v1/batches/retry/retry-image/bad.jpg").status_code in (
        404,
        409,
    )
    assert_safe(caplog, response.text)


def test_bulk_retry_partial_move_is_compensated(client, retry, monkeypatch, caplog):
    path, job = retry
    (path / "_errors" / "later.jpg").write_bytes(b"later")
    original = (path / "checkpoint.json").read_bytes()
    real_rename = Path.rename

    def rename(source, destination):
        if source.name == "later.jpg" and source.parent.name == "_errors":
            raise OSError(SECRET)
        return real_rename(source, destination)

    monkeypatch.setattr(Path, "rename", rename)
    response = client.post("/api/v1/batches/retry/retry")
    assert response.status_code == 500
    job.assert_not_called()
    assert (path / "_errors" / "bad.jpg").read_bytes() == b"original-image"
    assert (path / "_errors" / "later.jpg").read_bytes() == b"later"
    assert not (path / "bad.jpg").exists()
    assert (path / "checkpoint.json").read_bytes() == original
    assert not batch_manager.is_run_active("retry")
    assert_safe(caplog, response.text)


@pytest.mark.parametrize("endpoint", ["retry-image/bad.jpg", "retry"])
def test_valid_retry_preserves_other_results_and_audit(client, retry, endpoint):
    path, job = retry
    response = client.post(f"/api/v1/batches/retry/{endpoint}")
    assert response.status_code == 200
    job.assert_called_once()
    results, audit = read_checkpoint(path / "checkpoint.json")
    assert results == (
        [row()]
        if endpoint.startswith("retry-image")
        else [row(), row("bad.jpg", False)]
    )
    assert audit == [{"id": "keep"}]
    assert (path / "bad.jpg").read_bytes() == b"original-image"


def setup_run(monkeypatch, *, status="completed", processed=7):
    path = batch_manager.batches_dir / "bulk"
    path.mkdir()
    write_checkpoint(path / "checkpoint.json", [row()], [])
    run = make_run()
    run["folders"][0].update(
        batch_name="bulk", status=status, images_processed=processed, images_failed=1
    )
    bulk_manager.save_run(run)
    monkeypatch.setattr(settings, "BULK_IMPORT_ROOT", str(batch_manager.batches_dir))
    return path, run


@pytest.mark.parametrize("fault", ["corrupt", "unreadable", "missing"])
def test_count_failure_is_explicit_and_keeps_last_known_counts(
    client, monkeypatch, caplog, fault
):
    path, run = setup_run(monkeypatch)
    checkpoint = path / "checkpoint.json"
    if fault == "corrupt":
        checkpoint.write_text('{"' + SECRET)
    elif fault == "missing":
        checkpoint.unlink()
    else:
        monkeypatch.setattr(bulk_orchestrator, "read_checkpoint", fail)
    with pytest.raises(CheckpointError):
        bulk_orchestrator._folder_counts_from_checkpoint("bulk", required=True)
    response = client.post(f"/api/v1/bulk/runs/{run['bulk_run_id']}/start")
    assert response.status_code == 409
    state = client.get(f"/api/v1/bulk/runs/{run['bulk_run_id']}").json()
    assert state["status"] == "failed" and "last known" in state["error"]
    assert state["folders"][0]["images_processed"] == 7
    assert state["folders"][0]["images_failed"] == 1
    assert "not verified" in state["folders"][0]["error"]
    assert not bulk_manager.is_any_run_active()
    assert_safe(caplog, state, response.text)


def test_empty_checkpoint_is_a_verified_zero(monkeypatch):
    path, run = setup_run(monkeypatch)
    write_checkpoint(path / "checkpoint.json", [], [])
    assert bulk_orchestrator._folder_counts_from_checkpoint("bulk", required=True) == (
        0,
        0,
    )
    updated = bulk_orchestrator._reconcile_counts(run)
    assert not updated["checkpoint_error"] and updated["images_processed"] == 0


@pytest.mark.parametrize("suffix", ["export.csv", "failures.csv"])
@pytest.mark.parametrize("fault", ["corrupt", "unreadable", "missing"])
def test_bad_export_never_reports_success(
    client, monkeypatch, tmp_path, caplog, suffix, fault
):
    path, run = setup_run(monkeypatch)
    checkpoint = path / "checkpoint.json"
    if fault == "corrupt":
        checkpoint.write_text('{"' + SECRET)
    elif fault == "missing":
        checkpoint.unlink()
    else:
        monkeypatch.setattr(bulk_export, "read_checkpoint", fail)
    original = checkpoint.read_bytes() if checkpoint.exists() else None
    audit = tmp_path / "audit.jsonl"
    monkeypatch.setattr(settings, "AUDIT_ENABLED", True)
    monkeypatch.setattr(settings, "AUDIT_LOG_FILE", str(audit))
    export = bulk_manager.export_csv_path(run["bulk_run_id"])
    export.write_text("previous-valid-export")
    response = client.get(f"/api/v1/bulk/runs/{run['bulk_run_id']}/{suffix}")
    assert response.status_code == 500
    assert export.read_text() == "previous-valid-export"
    if original is not None:
        assert checkpoint.read_bytes() == original
    records = [json.loads(line) for line in audit.read_text().splitlines()]
    assert [r["result"] for r in records if r["action"] == "bulk_run_exported"] == [
        "failure"
    ]
    assert_safe(caplog, response.text, records)


@pytest.mark.parametrize(
    "status, kind, expected",
    [
        ("pending", "none", 200),
        ("pending", "missing", 200),
        ("running", "valid", 409),
        ("completed", "valid", 200),
        ("completed", "missing", 500),
        ("failed", "valid", 200),
        ("failed", "missing", 500),
    ],
)
def test_export_policy(client, monkeypatch, status, kind, expected):
    path, run = setup_run(monkeypatch, status=status, processed=0)
    folder = run["folders"][0]
    folder["images_failed"] = 0
    if kind == "none":
        folder["batch_name"] = None
    elif kind == "missing":
        (path / "checkpoint.json").unlink()
    bulk_manager.save_run(run)
    response = client.get(f"/api/v1/bulk/runs/{run['bulk_run_id']}/export.csv")
    assert response.status_code == expected
    if expected == 200:
        assert response.headers["x-export-scope"] == "available-checkpoints"


def test_actual_run_lock_blocks_export_even_with_stale_status(client, monkeypatch):
    _path, run = setup_run(monkeypatch)
    assert batch_manager.acquire_batch_lock("bulk")
    response = client.get(f"/api/v1/bulk/runs/{run['bulk_run_id']}/export.csv")
    assert response.status_code == 409


def test_late_checkpoint_read_failure_aborts_stream_and_audit(
    monkeypatch, tmp_path, caplog
):
    from test_delivery_security import server_request

    path, run = setup_run(monkeypatch)
    original = (path / "checkpoint.json").read_bytes()
    real_read = bulk_export.read_checkpoint
    reads = []

    def read(checkpoint):
        reads.append(checkpoint)
        if len(reads) == 2:  # After successful preflight and response-start.
            raise PermissionError(SECRET)
        return real_read(checkpoint)

    monkeypatch.setattr(bulk_export, "read_checkpoint", read)
    audit = tmp_path / "audit.jsonl"
    monkeypatch.setattr(settings, "AUDIT_ENABLED", True)
    monkeypatch.setattr(settings, "AUDIT_LOG_FILE", str(audit))
    cycle, transport, messages, wire = asyncio.run(
        server_request(f"/api/v1/bulk/runs/{run['bulk_run_id']}/failures.csv")
    )
    assert len(reads) == 2
    assert cycle.response_started and not cycle.response_complete
    transport.close.assert_called_once()
    assert not any(
        m["type"] == "http.response.body" and not m.get("more_body", False)
        for m in messages
    )
    records = [json.loads(line) for line in audit.read_text().splitlines()]
    assert [r["result"] for r in records] == ["failure"]
    assert (path / "checkpoint.json").read_bytes() == original
    assert_safe(caplog, records, wire)


def test_seed_count_failure_stops_driver_and_releases_batch_lock(monkeypatch, caplog):
    path, run = setup_run(monkeypatch, status="pending")
    (path / "checkpoint.json").write_text('{"' + SECRET)
    monkeypatch.setattr(
        bulk_orchestrator, "_validate_run_preconditions", lambda _: None
    )
    provider = Mock()
    monkeypatch.setattr(batches.ocr_engine, "_call_vlm_api_resilient", provider)
    assert bulk_manager.acquire_run_lock(run["bulk_run_id"])
    asyncio.run(bulk_orchestrator._drive(run["bulk_run_id"]))
    provider.assert_not_called()
    final = bulk_manager.get_run(run["bulk_run_id"])
    assert final["status"] == "failed" and "last known" in final["error"]
    assert final["folders"][0]["images_processed"] == 7
    assert not batch_manager.is_run_active("bulk")
    assert not bulk_manager.is_any_run_active()
    assert_safe(caplog, final)


@pytest.mark.parametrize("operation", ["count", "export"])
def test_missing_batch_reference_with_known_results_is_not_empty(
    monkeypatch, operation
):
    _path, run = setup_run(monkeypatch, status="pending", processed=7)
    run["folders"][0]["batch_name"] = None
    if operation == "count":
        state = bulk_orchestrator._reconcile_counts(run)
        assert state["status"] == "failed" and state["checkpoint_error"]
        assert state["folders"][0]["images_processed"] == 7
    else:
        with pytest.raises(CheckpointError):
            bulk_export.validate_export(run)


def test_integrity_latch_survives_reconcile_updates_replay_and_export(client, monkeypatch, caplog):
    from copy import deepcopy
    from app.services.bulk_progress import publish_bulk_progress

    _path, run = setup_run(monkeypatch, processed=0)
    folder = run["folders"][0]
    folder.update(batch_name=None, images_failed=0)
    bulk_manager.save_run(run)
    stale = deepcopy(run)
    for _ in range(2):
        run = bulk_orchestrator._reconcile_counts(run)
        bulk_manager.save_run(run)
        run = bulk_manager.get_run(run["bulk_run_id"])
        assert run["checkpoint_error"] and run["folders"][0]["integrity_error"]
    bulk_manager.save_run(stale)
    rid = run["bulk_run_id"]
    bulk_manager.update_folder(rid, folder["source_folder"], status="completed", error=None, integrity_error=None)
    bulk_manager.update_run(rid, status="completed", error=None, checkpoint_error=False)
    bulk_orchestrator._refresh_and_emit(rid)
    publish_bulk_progress(rid)
    http = client.get(f"/api/v1/bulk/runs/{rid}").json()
    with client.websocket_connect(f"/api/v1/ws/task/bulk:{rid}") as socket:
        replay = socket.receive_json()
    assert http == replay
    assert http["status"] == "failed" and http["folders"][0]["integrity_error"]
    assert "not verified" in http["error"]
    for suffix in ("export.csv", "failures.csv"):
        response = client.get(f"/api/v1/bulk/runs/{rid}/{suffix}")
        assert response.status_code == 500
        assert_safe(caplog, response.text)


@pytest.mark.parametrize("status", ["pending", "failed"])
def test_historical_unimported_folder_without_marker_remains_valid(client, monkeypatch, status):
    _path, run = setup_run(monkeypatch, status=status, processed=0)
    run["folders"][0].update(batch_name=None, images_failed=0, error="Import failed" if status == "failed" else None)
    reconciled = bulk_orchestrator._reconcile_counts(run)
    assert not reconciled["checkpoint_error"]
    bulk_manager.save_run(reconciled)
    assert client.get(f"/api/v1/bulk/runs/{run['bulk_run_id']}/export.csv").status_code == 200


def test_legacy_checkpoint_error_diagnostic_remains_latched(monkeypatch):
    _path, run = setup_run(monkeypatch, status="failed", processed=0)
    run["folders"][0].update(batch_name=None, images_failed=0, error="Checkpoint unavailable (checkpoint_invalid); counts are last known, not verified.")
    state = bulk_orchestrator._reconcile_counts(run)
    assert state["checkpoint_error"]
    with pytest.raises(CheckpointError):
        bulk_export.validate_export(state)


@pytest.mark.parametrize("fault", ["corrupt", "unreadable", "active", "association"])
def test_bulk_recovery_refuses_unverified_state(monkeypatch, fault):
    path, run = setup_run(monkeypatch)
    folder = run["folders"][0]
    folder["integrity_error"] = "checkpoint_invalid"
    bulk_manager.save_run(run)
    before = bulk_manager._run_json(run["bulk_run_id"]).read_bytes()
    if fault == "corrupt":
        (path / "checkpoint.json").write_text('{"' + SECRET)
    elif fault == "unreadable":
        import app.core.checkpoint as checkpoint
        monkeypatch.setattr(checkpoint, "read_checkpoint", fail)
    elif fault == "active":
        assert batch_manager.acquire_batch_lock("bulk")
    else:
        bulk_manager.update_folder(run["bulk_run_id"], folder["source_folder"], batch_name=None)
        before = bulk_manager._run_json(run["bulk_run_id"]).read_bytes()
    with pytest.raises((ValueError, OSError)):
        bulk_manager.recover_folder_integrity(run["bulk_run_id"], folder["source_folder"])
    assert bulk_manager._run_json(run["bulk_run_id"]).read_bytes() == before


def test_explicit_bulk_recovery_verifies_checkpoint_and_allows_export(client, monkeypatch):
    path, run = setup_run(monkeypatch)
    folder = run["folders"][0]
    folder["integrity_error"] = "checkpoint_invalid"
    bulk_manager.save_run(run)
    write_checkpoint(path / "checkpoint.json", [], [{"id": "keep"}])
    bulk_manager.save_run(bulk_orchestrator._reconcile_counts(bulk_manager.get_run(run["bulk_run_id"])))
    assert client.get(f"/api/v1/bulk/runs/{run['bulk_run_id']}/export.csv").status_code == 500
    recovered = bulk_manager.recover_folder_integrity(run["bulk_run_id"], folder["source_folder"])
    assert not recovered["checkpoint_error"] and recovered["status"] == "paused"
    assert recovered["images_processed"] == 0
    assert client.get(f"/api/v1/bulk/runs/{run['bulk_run_id']}/export.csv").status_code == 200
    assert read_checkpoint(path / "checkpoint.json") == ([], [{"id": "keep"}])


@pytest.mark.parametrize("operation", ["retry-image/bad.jpg", "retry", "start", "DELETE", "purge"])
def test_recovery_marker_blocks_followups_before_file_checks(client, retry, monkeypatch, caplog, operation):
    path, job = retry
    original = (path / "checkpoint.json").read_bytes()
    real_rename = Path.rename

    def rename(source, destination):
        if source.parent == path:
            raise OSError(SECRET)
        return real_rename(source, destination)

    monkeypatch.setattr(Path, "rename", rename)
    monkeypatch.setattr(batches, "write_checkpoint", fail)
    assert client.post("/api/v1/batches/retry/retry-image/bad.jpg").status_code == 500
    marker = path / ".retry-recovery.json"
    record = marker.read_bytes()
    assert json.loads(record)["code"] == "retry_recovery_required"
    assert SECRET not in record.decode()
    response = client.delete("/api/v1/batches/retry") if operation == "DELETE" else client.post(f"/api/v1/batches/retry/{operation}")
    assert response.status_code == 409 and "recovery" in response.text.lower()
    job.assert_not_called()
    assert marker.read_bytes() == record
    assert (path / "checkpoint.json").read_bytes() == original
    assert (path / "bad.jpg").read_bytes() == b"original-image"
    bulk_manager._release_interrupted_batch_lock("retry")
    batch_manager.release_batch_lock("retry")
    assert marker.read_bytes() == record and (path / ".run.lock").exists()
    assert not batch_manager.acquire_batch_lock("retry")
    assert_safe(caplog, response.text)


@pytest.mark.parametrize("prepared", [False, True])
def test_retry_admin_recovery_requires_verified_original_or_prepared_state(retry, prepared):
    path, _job = retry
    original = (path / "checkpoint.json").read_bytes()
    assert batch_manager.acquire_batch_lock("retry")
    rows, audit = read_checkpoint(path / "checkpoint.json")
    after = {"results": [r for r in rows if r["filename"] != "bad.jpg"], "audit": audit}
    batch_manager.begin_retry_preparation("retry", [path / "_errors" / "bad.jpg"], after)
    (path / "_errors" / "bad.jpg").rename(path / "bad.jpg")
    with pytest.raises((ValueError, OSError)):
        batch_manager.recover_retry("retry")
    assert batch_manager.retry_recovery_required("retry")
    if prepared:
        write_checkpoint(path / "checkpoint.json", after["results"], audit)
    else:
        (path / "bad.jpg").rename(path / "_errors" / "bad.jpg")
    batch_manager.recover_retry("retry", prepared=prepared)
    assert not batch_manager.is_run_active("retry")
    assert not batch_manager.retry_recovery_required("retry")
    if not prepared:
        assert (path / "checkpoint.json").read_bytes() == original
    assert batch_manager.acquire_batch_lock("retry")
    batch_manager.release_batch_lock("retry")
    assert not batch_manager.is_run_active("retry")


def test_regular_lock_is_unchanged(retry):
    path, _job = retry
    assert batch_manager.acquire_batch_lock("retry")
    assert not batch_manager.retry_recovery_required("retry")
    assert not batch_manager.acquire_batch_lock("retry")
    batch_manager.release_batch_lock("retry")
    assert not batch_manager.is_run_active("retry")
    assert not (path / ".retry-recovery.json").exists()


def test_successive_retries_reach_real_engine_without_network(client, monkeypatch):
    path = batch_manager.batches_dir / "successive"
    (path / "_errors").mkdir(parents=True)
    for name in ("one.jpg", "two.jpg"):
        (path / "_errors" / name).write_bytes(b"mock-image")
    (path / "config.json").write_text('{"provider":"ollama"}')
    write_checkpoint(path / "checkpoint.json", [row("one.jpg", False), row("two.jpg", False)], [{"id":"preserved"}])
    monkeypatch.setattr(batches, "_resolve_provider", lambda *_: ("http://unused", "mock", None))
    calls = []

    def provider(image, *args, **kwargs):
        calls.append(image.name)
        return {"fields": {"Komponist": "Mock", "Signatur": "Spez. 1"}}, None

    network = Mock(side_effect=AssertionError("Unexpected network request"))
    monkeypatch.setattr(batches.ocr_engine.session, "post", network)
    monkeypatch.setattr(batches.ocr_engine, "_call_vlm_api_resilient", provider)
    for name in ("one.jpg", "two.jpg"):
        response = client.post(f"/api/v1/batches/successive/retry-image/{name}")
        assert response.status_code == 200
        rows, audit = read_checkpoint(path / "checkpoint.json")
        assert next(r for r in rows if r["filename"] == name)["success"]
        assert audit == [{"id":"preserved"}]
        assert not batch_manager.is_run_active("successive")
    assert calls == ["one.jpg", "two.jpg"]
    network.assert_not_called()
    assert len(rows) == 2 and all(r["success"] for r in rows)


@pytest.mark.parametrize("stage", ["write", "fsync", "replace"])
def test_recovery_intent_write_failure_prevents_any_image_move(client, retry, monkeypatch, caplog, stage):
    path, job = retry
    checkpoint = (path / "checkpoint.json").read_bytes()
    if stage == "write":
        monkeypatch.setattr(atomic_io, "atomic_write_text", fail)
    else:
        monkeypatch.setattr(atomic_io.os, stage, fail)
    response = client.post("/api/v1/batches/retry/retry-image/bad.jpg")
    assert response.status_code == 500
    job.assert_not_called()
    assert (path / "_errors" / "bad.jpg").read_bytes() == b"original-image"
    assert not (path / "bad.jpg").exists()
    assert (path / "checkpoint.json").read_bytes() == checkpoint
    assert not batch_manager.retry_recovery_required("retry")
    assert not batch_manager.is_run_active("retry")
    assert_safe(caplog, response.text)


def test_marker_cleanup_failure_requires_explicit_verified_prepared_recovery(client, retry, monkeypatch, caplog):
    path, job = retry
    real_unlink = Path.unlink

    def unlink(target, *args, **kwargs):
        if target.name == ".retry-recovery.json":
            raise OSError(SECRET)
        return real_unlink(target, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", unlink)
        response = client.post("/api/v1/batches/retry/retry-image/bad.jpg")
    assert response.status_code == 500 and "recovery" in response.text.lower()
    job.assert_not_called()
    assert batch_manager.retry_recovery_required("retry")
    assert (path / "bad.jpg").read_bytes() == b"original-image"
    rows, audit = read_checkpoint(path / "checkpoint.json")
    assert [r["filename"] for r in rows] == ["done.jpg"] and audit == [{"id": "keep"}]
    with pytest.raises(ValueError):
        batch_manager.recover_retry("retry")
    batch_manager.recover_retry("retry", prepared=True)
    assert not batch_manager.is_run_active("retry")
    assert_safe(caplog, response.text)


def test_recovery_marker_blocks_even_without_pid_lock(retry):
    path, _job = retry
    assert batch_manager.acquire_batch_lock("retry")
    batch_manager.begin_retry_preparation("retry", [path / "_errors" / "bad.jpg"])
    (path / ".run.lock").unlink()
    bulk_manager._release_interrupted_batch_lock("retry")
    assert batch_manager.is_run_active("retry")
    assert not batch_manager.acquire_batch_lock("retry")
    with pytest.raises(RuntimeError):
        batch_manager.delete_batch("retry")
    with pytest.raises(RuntimeError):
        batch_manager.purge_batch_data("retry")
    batch_manager.recover_retry("retry")
    assert not batch_manager.is_run_active("retry")


def test_integrity_latch_survives_dropped_folder_projection(monkeypatch):
    _path, run = setup_run(monkeypatch)
    run["folders"][0]["integrity_error"] = "checkpoint_unreadable"
    bulk_manager.save_run(run)
    bulk_manager.update_run(run["bulk_run_id"], folders=[], status="completed")
    saved = bulk_manager.get_run(run["bulk_run_id"])
    assert saved["status"] == "failed" and saved["folders"][0]["integrity_error"]
