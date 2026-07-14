"""Retention + purge tests (audit finding I-3)."""
import json
from datetime import datetime, timedelta

from app.core.config import settings
from app.services import retention
from app.services.batch_manager import batch_manager


def _make_batch(name: str, status: str, completed_days_ago: float | None):
    """Create a batch dir + history entry directly (bypasses OCR)."""
    bpath = batch_manager.batches_dir / name
    bpath.mkdir(parents=True, exist_ok=True)
    (bpath / "checkpoint.json").write_text('{"results": [], "audit": []}')
    (bpath / "card.jpg").write_bytes(b"\xff\xd8\xff\xe0data\xff\xd9")
    entry = {"batch_name": name, "custom_name": name, "created_at": "2026-01-01T00:00:00", "status": status}
    if completed_days_ago is not None:
        entry["completed_at"] = (datetime.now() - timedelta(days=completed_days_ago)).isoformat()
    history = batch_manager._read_history_raw()
    history = [e for e in history if e.get("batch_name") != name]
    history.append(entry)
    batch_manager._write_history_raw(history)
    return bpath


def test_preview_disabled_by_default(client):
    assert settings.RETENTION_DAYS == 0
    p = retention.preview_purgeable()
    assert p["enabled"] is False
    assert p["eligible"] == []


def test_sweep_noop_when_disabled(client, monkeypatch):
    monkeypatch.setattr(settings, "RETENTION_DAYS", 0)
    _make_batch("old_completed_x", "completed", completed_days_ago=999)
    result = retention.run_retention_sweep()
    assert result["enabled"] is False
    assert result["purged"] == []
    assert (batch_manager.batches_dir / "old_completed_x").exists()  # untouched


def test_only_old_completed_batches_eligible(client, monkeypatch):
    monkeypatch.setattr(settings, "RETENTION_DAYS", 30)
    _make_batch("ret_old_done", "completed", completed_days_ago=40)     # eligible
    _make_batch("ret_new_done", "completed", completed_days_ago=5)      # too new
    _make_batch("ret_failed", "failed", completed_days_ago=99)          # not completed
    _make_batch("ret_running", "running", completed_days_ago=None)      # active status

    preview = retention.preview_purgeable()
    eligible = {e["batch_name"] for e in preview["eligible"]}
    assert "ret_old_done" in eligible
    assert "ret_new_done" not in eligible
    assert "ret_failed" not in eligible
    assert "ret_running" not in eligible


def test_active_run_never_purged(client, monkeypatch):
    monkeypatch.setattr(settings, "RETENTION_DAYS", 30)
    _make_batch("ret_locked", "completed", completed_days_ago=40)
    assert batch_manager.acquire_batch_lock("ret_locked")  # simulate active run
    try:
        preview = retention.preview_purgeable()
        names = {e["batch_name"] for e in preview["eligible"]}
        assert "ret_locked" not in names
    finally:
        batch_manager.release_batch_lock("ret_locked")


def test_sweep_purges_and_keeps_tombstone(client, monkeypatch):
    monkeypatch.setattr(settings, "RETENTION_DAYS", 30)
    _make_batch("ret_purge_me", "completed", completed_days_ago=45)
    result = retention.run_retention_sweep()
    assert "ret_purge_me" in result["purged"]
    # Data gone…
    assert not (batch_manager.batches_dir / "ret_purge_me").exists()
    # …but a non-sensitive tombstone remains for accountability.
    history = batch_manager._read_history_raw()
    entry = next(e for e in history if e["batch_name"] == "ret_purge_me")
    assert entry["status"] == "purged"
    assert "purged_at" in entry


def test_manual_purge_endpoint(client, monkeypatch):
    _make_batch("ret_manual", "completed", completed_days_ago=1)
    r = client.post("/api/v1/batches/ret_manual/purge")
    assert r.status_code == 200
    assert r.json()["batch_name"] == "ret_manual"
    assert not (batch_manager.batches_dir / "ret_manual").exists()


def test_manual_purge_blocked_while_running(client):
    _make_batch("ret_manual_locked", "completed", completed_days_ago=1)
    assert batch_manager.acquire_batch_lock("ret_manual_locked")
    try:
        r = client.post("/api/v1/batches/ret_manual_locked/purge")
        assert r.status_code == 409
        assert (batch_manager.batches_dir / "ret_manual_locked").exists()  # not deleted
    finally:
        batch_manager.release_batch_lock("ret_manual_locked")


def test_preview_endpoint(client):
    r = client.get("/api/v1/batches/retention/preview")
    assert r.status_code == 200
    assert "eligible" in r.json() and "skipped" in r.json()


# --------------------------------------------------------------------------- #
# Authority cache TTL (audit I-3)
# --------------------------------------------------------------------------- #
def test_cache_ttl_expires_old_entries(client, monkeypatch, tmp_path):
    from app.services.authority import cache

    monkeypatch.setattr(settings, "AUTHORITY_CACHE_TTL_DAYS", 7)
    bdir = tmp_path / "cachebatch"
    bdir.mkdir()

    # Write an entry, then backdate its timestamp beyond the TTL.
    cache.write_cache_entry(bdir, "gnd-persons", "Bach", [{"label": "x", "uri": "y"}])
    raw = json.loads((bdir / "authority_cache.json").read_text())
    key = next(iter(raw))
    raw[key]["ts"] = (datetime.now() - timedelta(days=30)).astimezone().isoformat()
    (bdir / "authority_cache.json").write_text(json.dumps(raw))

    # Expired → treated as a miss.
    assert cache.lookup_cache(bdir, "gnd-persons", "Bach") is None


def test_cache_no_ttl_keeps_entries(client, monkeypatch, tmp_path):
    from app.services.authority import cache

    monkeypatch.setattr(settings, "AUTHORITY_CACHE_TTL_DAYS", 0)  # no expiry
    bdir = tmp_path / "cachebatch2"
    bdir.mkdir()
    cache.write_cache_entry(bdir, "wikidata", "Mozart", [{"label": "m", "uri": "u"}])
    result = cache.lookup_cache(bdir, "wikidata", "Mozart")
    assert result == [{"label": "m", "uri": "u"}]
