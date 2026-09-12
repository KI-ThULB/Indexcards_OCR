"""REST + WebSocket surface: gating, auth, validation, audit, export downloads."""
import csv
import io
import json

import time

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.core.rate_limit import limiter
from app.models.schemas import TemplateCreate, TemplateUpdate
from app.services.batch_manager import batch_manager
from app.services.bulk_manager import (
    STATUS_INTERRUPTED,
    STATUS_PAUSED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    bulk_manager,
)
from app.services.bulk_progress import bulk_channel
from app.services.ocr_engine import ocr_engine
from app.services.template_service import template_service
from app.services.ws_manager import ws_manager

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16 + b"\xff\xd9"
FIELDS = ["Komponist", "Signatur"]


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """slowapi counters are process-global and this module hits the rate-limited
    create/start routes far more often than a curator would. The limit itself is
    covered by test_rate_limit_on_create."""
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture(autouse=True)
def _clean_state():
    before = set(batch_manager.list_batches())
    yield
    bulk_manager.release_run_lock()
    for name in set(batch_manager.list_batches()) - before:
        try:
            batch_manager.release_batch_lock(name)
            batch_manager.delete_batch(name)
        except Exception:
            pass


@pytest.fixture
def import_root(tmp_path, monkeypatch):
    root = tmp_path / "amiga"
    for i in range(1, 4):
        folder = root / f"Batch_{i:03d}"
        folder.mkdir(parents=True)
        (folder / f"IMG_{i}_a.JPG").write_bytes(JPEG)
        (folder / f"IMG_{i}_b.jpeg").write_bytes(JPEG)
    monkeypatch.setattr(settings, "BULK_IMPORT_ROOT", str(root))
    return root


@pytest.fixture
def runs_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(bulk_manager, "runs_dir", tmp_path / "bulk_runs")
    return bulk_manager.runs_dir


@pytest.fixture
def template():
    # Real model, not a duck-typed double — see the note in test_bulk_run.py.
    tpl = template_service.create_template(TemplateCreate(name="AMIGA", fields=FIELDS))
    yield tpl
    template_service.delete_template(tpl.id)


@pytest.fixture
def mock_vlm(monkeypatch):
    monkeypatch.setattr(
        ocr_engine, "_call_vlm_api_resilient",
        lambda *a, **k: ({"fields": {"Komponist": "Bach", "Signatur": "S1"}}, None),
    )


@pytest.fixture
def live_client():
    """A context-managed client, so one event loop spans several requests.

    The orchestrator runs as an asyncio task on the server's loop. A plain
    TestClient(app) call spins up a loop per request and tears it down on
    return, which cancels that task; entering the context manager keeps one
    portal (and one loop) alive across requests, like a real uvicorn process.
    """
    with TestClient(app) as c:
        yield c


def _wait_terminal(client, run_id: str, timeout: float = 20.0) -> dict:
    """Poll until the run reaches a terminal/paused state. The orchestrator runs
    on the portal's loop in a background thread, so sleeping here lets it run."""
    deadline = time.time() + timeout
    terminal = {"completed", "completed_with_errors", "failed", "cancelled", "paused"}
    while time.time() < deadline:
        run = client.get(f"/api/v1/bulk/runs/{run_id}").json()
        if run["status"] in terminal:
            return run
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} did not finish: {run['status']}")


def _create(client, template, folders=("Batch_001", "Batch_002")):
    resp = client.post("/api/v1/bulk/runs", json={
        "name": "AMIGA Tonbandkartei",
        "template_id": template.id,
        "folders": list(folders),
        "provider": "ollama",
        "model": "qwen3-vl:235b",
    })
    assert resp.status_code == 200, resp.text
    return resp.json()


# --------------------------------------------------------------------------- #
# Disabled by default → no bulk surface at all
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/v1/bulk/sources"),
        ("get", "/api/v1/bulk/runs"),
        ("get", "/api/v1/bulk/runs/11111111-1111-4111-8111-111111111111"),
        ("get", "/api/v1/bulk/runs/11111111-1111-4111-8111-111111111111/export.csv"),
        ("get", "/api/v1/bulk/runs/11111111-1111-4111-8111-111111111111/failures.csv"),
        ("post", "/api/v1/bulk/runs"),
        ("post", "/api/v1/bulk/runs/11111111-1111-4111-8111-111111111111/start"),
        ("post", "/api/v1/bulk/runs/11111111-1111-4111-8111-111111111111/resume"),
        ("post", "/api/v1/bulk/runs/11111111-1111-4111-8111-111111111111/pause"),
        ("post", "/api/v1/bulk/runs/11111111-1111-4111-8111-111111111111/cancel"),
    ],
)
def test_all_routes_404_when_disabled(client, method, path):
    resp = (
        client.post(path, json={}) if method == "post" else client.get(path)
    )
    assert resp.status_code == 404


def test_config_reports_bulk_disabled_by_default(client):
    assert client.get("/api/v1/config").json()["bulk_enabled"] is False


def test_config_reports_bulk_enabled_when_configured(client, import_root):
    assert client.get("/api/v1/config").json()["bulk_enabled"] is True


def test_config_never_leaks_the_import_root(client, import_root):
    assert str(import_root) not in client.get("/api/v1/config").text


# --------------------------------------------------------------------------- #
# Authentication
# --------------------------------------------------------------------------- #
def test_auth_enforced_on_bulk_routes(client, import_root, auth_token):
    assert client.get("/api/v1/bulk/sources").status_code == 401
    assert client.post("/api/v1/bulk/runs", json={}).status_code == 401

    ok = client.get(
        "/api/v1/bulk/sources", headers={"Authorization": f"Bearer {auth_token}"}
    )
    assert ok.status_code == 200


def test_wrong_token_rejected(client, import_root, auth_token):
    resp = client.get("/api/v1/bulk/sources", headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 401


# --------------------------------------------------------------------------- #
# Sources
# --------------------------------------------------------------------------- #
def test_sources_lists_folders_with_counts(client, import_root):
    body = client.get("/api/v1/bulk/sources").json()
    assert body["root_configured"] is True
    assert body["truncated"] is False
    assert [f["name"] for f in body["folders"]] == ["Batch_001", "Batch_002", "Batch_003"]
    assert all(f["images_total"] == 2 for f in body["folders"])


# --------------------------------------------------------------------------- #
# Create validation
# --------------------------------------------------------------------------- #
def test_create_run_freezes_the_schema(client, import_root, runs_dir, template):
    run = _create(client, template)
    assert run["status"] == STATUS_QUEUED
    assert run["schema_fields"] == FIELDS
    assert run["folders_total"] == 2
    assert run["images_total"] == 4
    assert [f["source_folder"] for f in run["folders"]] == ["Batch_001", "Batch_002"]




def test_gpustack_create_freezes_default_alias(
    client, import_root, runs_dir, template, monkeypatch
):
    monkeypatch.setattr(settings, "GPUSTACK_ENABLED", True)
    monkeypatch.setattr(settings, "GPUSTACK_API_KEY", "test-key-not-used")
    monkeypatch.setattr(settings, "GPUSTACK_DEFAULT_MODEL", "stable-vlm")

    resp = client.post("/api/v1/bulk/runs", json={
        "name": "GPUStack probe",
        "template_id": template.id,
        "folders": ["Batch_001"],
        "provider": "gpustack",
        "model": None,
    })
    assert resp.status_code == 200, resp.text
    run = resp.json()
    assert run["provider"] == "gpustack"
    assert run["model"] == "stable-vlm"

    # Changing the backend default after creation must not alter this run.
    monkeypatch.setattr(settings, "GPUSTACK_DEFAULT_MODEL", "future-vlm")
    detail = client.get(f"/api/v1/bulk/runs/{run['bulk_run_id']}").json()
    assert detail["model"] == "stable-vlm"

def test_created_run_survives_a_later_template_edit(client, import_root, runs_dir, template):
    run = _create(client, template)
    template_service.update_template(
        template.id, TemplateUpdate(fields=["Voellig", "Andere", "Felder"])
    )
    detail = client.get(f"/api/v1/bulk/runs/{run['bulk_run_id']}").json()
    assert detail["schema_fields"] == FIELDS, "schema_fields must be frozen at creation"


@pytest.mark.parametrize("folders", [[], ["Batch_001", "Batch_001"]])
def test_create_rejects_bad_folder_selection(client, import_root, runs_dir, template, folders):
    resp = client.post("/api/v1/bulk/runs", json={
        "name": "x", "template_id": template.id, "folders": folders,
    })
    assert resp.status_code == 400


@pytest.mark.parametrize("evil", ["../", "../../etc", "/etc/passwd", "Batch_001/nested", ".."])
def test_create_rejects_traversal_in_folder_names(client, import_root, runs_dir, template, evil):
    resp = client.post("/api/v1/bulk/runs", json={
        "name": "x", "template_id": template.id, "folders": [evil],
    })
    assert resp.status_code == 400
    assert "Unknown source folder" in resp.text


def test_create_rejects_unknown_template(client, import_root, runs_dir):
    resp = client.post("/api/v1/bulk/runs", json={
        "name": "x", "template_id": "no-such-template", "folders": ["Batch_001"],
    })
    assert resp.status_code == 404


def test_create_rejects_unknown_provider(client, import_root, runs_dir, template):
    resp = client.post("/api/v1/bulk/runs", json={
        "name": "x", "template_id": template.id, "folders": ["Batch_001"], "provider": "skynet",
    })
    assert resp.status_code == 400


def test_create_rejects_more_folders_than_the_cap(
    client, import_root, runs_dir, template, monkeypatch
):
    monkeypatch.setattr(settings, "BULK_MAX_FOLDERS", 1)
    resp = client.post("/api/v1/bulk/runs", json={
        "name": "x", "template_id": template.id, "folders": ["Batch_001", "Batch_002"],
    })
    assert resp.status_code == 400


def test_create_rejects_empty_folder(client, import_root, runs_dir, template):
    (import_root / "Batch_empty").mkdir()
    resp = client.post("/api/v1/bulk/runs", json={
        "name": "x", "template_id": template.id, "folders": ["Batch_empty"],
    })
    assert resp.status_code == 400


def test_run_name_is_never_used_as_a_path(client, import_root, runs_dir, template):
    """The run name is display text; the run directory is the uuid."""
    resp = client.post("/api/v1/bulk/runs", json={
        "name": "../../etc/passwd", "template_id": template.id, "folders": ["Batch_001"],
    })
    assert resp.status_code == 200
    run_id = resp.json()["bulk_run_id"]
    assert (runs_dir / run_id / "run.json").exists()
    assert {p.name for p in runs_dir.iterdir()} == {run_id}


# --------------------------------------------------------------------------- #
# Lifecycle
# --------------------------------------------------------------------------- #
def test_start_processes_the_run(live_client, import_root, runs_dir, template, mock_vlm):
    run = _create(live_client, template)
    resp = live_client.post(f"/api/v1/bulk/runs/{run['bulk_run_id']}/start")
    assert resp.status_code == 200, resp.text

    final = _wait_terminal(live_client, run["bulk_run_id"])
    assert final["status"] == "completed"
    assert final["images_processed"] == 4
    assert final["folders_completed"] == 2


def test_start_refuses_a_non_queued_run(live_client, import_root, runs_dir, template, mock_vlm):
    run = _create(live_client, template)
    live_client.post(f"/api/v1/bulk/runs/{run['bulk_run_id']}/start")
    _wait_terminal(live_client, run["bulk_run_id"])
    again = live_client.post(f"/api/v1/bulk/runs/{run['bulk_run_id']}/start")
    assert again.status_code == 409
    assert "resume" in again.text


def test_resume_refuses_a_completed_run(live_client, import_root, runs_dir, template, mock_vlm):
    run = _create(live_client, template)
    live_client.post(f"/api/v1/bulk/runs/{run['bulk_run_id']}/start")
    _wait_terminal(live_client, run["bulk_run_id"])
    resp = live_client.post(f"/api/v1/bulk/runs/{run['bulk_run_id']}/resume")
    assert resp.status_code == 409


def test_resume_after_interruption(live_client, import_root, runs_dir, template, mock_vlm):
    """The documented restart walkthrough, through the API."""
    run = _create(live_client, template)
    run_id = run["bulk_run_id"]
    bulk_manager.update_run(run_id, status=STATUS_RUNNING, current_folder="Batch_001",
                            last_image="IMG_1_a.JPG")

    # ── backend restart ──
    bulk_manager.mark_interrupted_runs()

    detail = live_client.get(f"/api/v1/bulk/runs/{run_id}").json()
    assert detail["status"] == STATUS_INTERRUPTED
    assert detail["interrupted_at"]
    assert detail["current_folder"] == "Batch_001"
    assert detail["last_image"] == "IMG_1_a.JPG"

    # ── explicit Resume ──
    assert live_client.post(f"/api/v1/bulk/runs/{run_id}/resume").status_code == 200
    assert _wait_terminal(live_client, run_id)["status"] == "completed"


def test_pause_and_cancel_refuse_a_non_running_run(client, import_root, runs_dir, template):
    run = _create(client, template)
    assert client.post(f"/api/v1/bulk/runs/{run['bulk_run_id']}/pause").status_code == 409
    assert client.post(f"/api/v1/bulk/runs/{run['bulk_run_id']}/cancel").status_code == 409


def test_pause_marks_the_request(client, import_root, runs_dir, template):
    run = _create(client, template)
    bulk_manager.update_run(run["bulk_run_id"], status=STATUS_RUNNING)
    resp = client.post(f"/api/v1/bulk/runs/{run['bulk_run_id']}/pause")
    assert resp.status_code == 200
    assert resp.json()["pause_requested"] is True


def test_unknown_run_is_404(client, import_root, runs_dir):
    assert client.get("/api/v1/bulk/runs/11111111-1111-4111-8111-111111111111").status_code == 404
    assert client.get("/api/v1/bulk/runs/not-a-uuid").status_code == 404


def test_list_runs(client, import_root, runs_dir, template):
    a = _create(client, template, folders=("Batch_001",))
    b = _create(client, template, folders=("Batch_002",))
    ids = [r["bulk_run_id"] for r in client.get("/api/v1/bulk/runs").json()]
    assert set(ids) == {a["bulk_run_id"], b["bulk_run_id"]}


# --------------------------------------------------------------------------- #
# Export downloads
# --------------------------------------------------------------------------- #
def test_export_csv_download(live_client, import_root, runs_dir, template, mock_vlm):
    client = live_client
    run = _create(client, template)
    client.post(f"/api/v1/bulk/runs/{run['bulk_run_id']}/start")
    _wait_terminal(client, run["bulk_run_id"])

    resp = client.get(f"/api/v1/bulk/runs/{run['bulk_run_id']}/export.csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "AMIGA_Tonbandkartei_consolidated.csv" in resp.headers["content-disposition"]

    text = resp.content.decode("utf-8")
    assert text.startswith("﻿")
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    assert rows[0][:4] == ["bulk_run_id", "source_folder", "source_filename", "batch_id"]
    assert len(rows) == 1 + 4
    assert {r[1] for r in rows[1:]} == {"Batch_001", "Batch_002"}
    # The artefact is persisted alongside the run state.
    assert (runs_dir / run["bulk_run_id"] / "consolidated.csv").exists()


def test_export_csv_is_stable_across_downloads(live_client, import_root, runs_dir, template, mock_vlm):
    client = live_client
    run = _create(client, template)
    client.post(f"/api/v1/bulk/runs/{run['bulk_run_id']}/start")
    _wait_terminal(client, run["bulk_run_id"])
    first = client.get(f"/api/v1/bulk/runs/{run['bulk_run_id']}/export.csv").content
    second = client.get(f"/api/v1/bulk/runs/{run['bulk_run_id']}/export.csv").content
    assert first == second


def test_failures_csv_download(live_client, import_root, runs_dir, template, monkeypatch):
    def fake(image_path, *a, **k):
        if image_path.name == "IMG_1_b.jpeg":
            return None, "HTTP 500: upstream"
        return {"fields": {"Komponist": "Bach"}}, None

    monkeypatch.setattr(ocr_engine, "_call_vlm_api_resilient", fake)
    run = _create(live_client, template)
    live_client.post(f"/api/v1/bulk/runs/{run['bulk_run_id']}/start")
    _wait_terminal(live_client, run["bulk_run_id"])

    resp = live_client.get(f"/api/v1/bulk/runs/{run['bulk_run_id']}/failures.csv")
    assert resp.status_code == 200
    rows = list(csv.reader(io.StringIO(resp.content.decode("utf-8").lstrip("﻿"))))
    assert [r[2] for r in rows[1:]] == ["IMG_1_b.jpeg"]


# --------------------------------------------------------------------------- #
# WebSocket
# --------------------------------------------------------------------------- #
def test_bulk_progress_channel_replays_last_state(
    live_client, import_root, runs_dir, template, mock_vlm
):
    """A browser reload must pick the running job back up — the ws_manager's
    existing replay-on-connect gives that for free on the bulk channel too."""
    client = live_client
    run = _create(client, template)
    run_id = run["bulk_run_id"]
    client.post(f"/api/v1/bulk/runs/{run_id}/start")
    _wait_terminal(client, run_id)

    channel = bulk_channel(run_id)
    assert channel in ws_manager.bulk_states

    with client.websocket_connect(f"/api/v1/ws/task/{channel}") as ws:
        state = json.loads(ws.receive_text())
    assert state["bulk_run_id"] == run_id
    assert state["status"] == "completed"
    assert state["folders_total"] == 2


def test_bulk_websocket_rejects_a_cross_site_origin(client, import_root, runs_dir, template):
    from starlette.websockets import WebSocketDisconnect

    run = _create(client, template)
    channel = bulk_channel(run["bulk_run_id"])
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            f"/api/v1/ws/task/{channel}", headers={"origin": "https://evil.example"}
        ) as ws:
            ws.receive_text()


def test_bulk_websocket_requires_the_token(client, import_root, auth_token):
    from starlette.websockets import WebSocketDisconnect

    channel = "bulk:11111111-1111-4111-8111-111111111111"
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/api/v1/ws/task/{channel}") as ws:
            ws.receive_text()


def test_progress_payload_carries_no_extracted_metadata(
    live_client, import_root, runs_dir, template, mock_vlm
):
    client = live_client
    run = _create(client, template)
    client.post(f"/api/v1/bulk/runs/{run['bulk_run_id']}/start")
    _wait_terminal(client, run["bulk_run_id"])
    payload = client.get(f"/api/v1/bulk/runs/{run['bulk_run_id']}").text
    assert "Bach" not in payload
    for key in ('"data"', '"edited_data"', '"confidence"'):
        assert key not in payload


# --------------------------------------------------------------------------- #
# Audit
# --------------------------------------------------------------------------- #
def _audit_actions(monkeypatch=None) -> list:
    from pathlib import Path
    path = Path(settings.AUDIT_LOG_FILE)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_audit_events_are_emitted(live_client, import_root, runs_dir, template, mock_vlm):
    client = live_client
    before = len(_audit_actions())
    run = _create(client, template)
    client.post(f"/api/v1/bulk/runs/{run['bulk_run_id']}/start")
    _wait_terminal(client, run["bulk_run_id"])
    client.get(f"/api/v1/bulk/runs/{run['bulk_run_id']}/export.csv")

    new = _audit_actions()[before:]
    actions = [r["action"] for r in new]
    assert "bulk_run_created" in actions
    assert "bulk_run_started" in actions
    assert "bulk_run_completed" in actions
    assert "bulk_run_exported" in actions


def test_audit_records_carry_no_metadata(live_client, import_root, runs_dir, template, mock_vlm):
    client = live_client
    before = len(_audit_actions())
    run = _create(client, template)
    client.post(f"/api/v1/bulk/runs/{run['bulk_run_id']}/start")
    _wait_terminal(client, run["bulk_run_id"])
    client.get(f"/api/v1/bulk/runs/{run['bulk_run_id']}/export.csv")

    for record in _audit_actions()[before:]:
        raw = json.dumps(record)
        assert "Bach" not in raw, "audit must never contain extracted metadata"
        assert str(import_root) not in raw
        for forbidden in ("api_key", "token", "prompt", "Authorization"):
            assert forbidden not in raw


def test_pause_and_cancel_are_audited(client, import_root, runs_dir, template):
    run = _create(client, template)
    bulk_manager.update_run(run["bulk_run_id"], status=STATUS_RUNNING)
    before = len(_audit_actions())
    client.post(f"/api/v1/bulk/runs/{run['bulk_run_id']}/pause")
    bulk_manager.update_run(run["bulk_run_id"], status=STATUS_RUNNING)
    client.post(f"/api/v1/bulk/runs/{run['bulk_run_id']}/cancel")

    actions = [r["action"] for r in _audit_actions()[before:]]
    assert "bulk_run_paused" in actions
    assert "bulk_run_cancelled" in actions


def test_resume_is_audited(client, import_root, runs_dir, template, mock_vlm):
    run = _create(client, template)
    bulk_manager.update_run(run["bulk_run_id"], status=STATUS_PAUSED)
    before = len(_audit_actions())
    client.post(f"/api/v1/bulk/runs/{run['bulk_run_id']}/resume")
    assert "bulk_run_resumed" in [r["action"] for r in _audit_actions()[before:]]


# --------------------------------------------------------------------------- #
# Rate limiting
# --------------------------------------------------------------------------- #
def test_rate_limit_on_create(client, import_root, runs_dir, template, monkeypatch):
    """Creating runs is rate limited, so an automated client cannot spin up
    unbounded VLM work."""
    limiter.reset()
    payload = {"name": "x", "template_id": template.id, "folders": ["Batch_001"]}
    statuses = [
        client.post("/api/v1/bulk/runs", json=payload).status_code for _ in range(12)
    ]
    assert 429 in statuses, f"expected a 429 within the limit window, got {statuses}"
    limiter.reset()
