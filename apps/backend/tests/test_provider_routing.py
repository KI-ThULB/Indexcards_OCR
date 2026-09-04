"""Provider routing: what the operator selects is what the engine actually calls.

A bulk run configured for local Ollama once sent every card to OpenRouter. The
provider was frozen in run.json, but the orchestrator called run_ocr_task
without it and run_ocr_task defaulted to "openrouter", so the selection was
recorded and displayed while the traffic went somewhere else entirely.

Every assertion here intercepts ``ocr_engine.session.post`` — the engine's only
outbound call. That is deliberate: the pre-existing bulk tests mocked
``process_batch`` (and the older ones ``_call_vlm_api_resilient``), which sits
*above* provider resolution, which is precisely why the bug survived them. No
network is touched; no provider is contacted.
"""
import asyncio
import json
import time

import pytest

from app.api.api_v1.endpoints.batches import (
    ProviderConfigurationError,
    _resolve_provider,
    provider_endpoint_host,
    run_ocr_task,
)
from app.core.checkpoint import read_checkpoint
from app.core.config import settings
from app.services import bulk_import, bulk_orchestrator
from app.services.batch_manager import batch_manager
from app.services.bulk_manager import STATUS_FAILED, bulk_manager
from app.services.ocr_engine import ocr_engine
from app.services.template_service import template_service

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16 + b"\xff\xd9"
FIELDS = ["Komponist", "Signatur"]
OLLAMA_MODEL = "qwen3-vl:235b"
# Comfortably more than MAX_WORKERS, so a stop leaves a queue to cancel.
CARDS = 24


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _dummy_credentials(monkeypatch):
    """Give both providers a non-empty placeholder key.

    The engine returns "API Key missing" *before* issuing a request when a key
    is empty, so on a machine without OPENROUTER_API_KEY these routing
    assertions would see zero requests and fail for a reason that has nothing to
    do with routing. Placeholder values only — no request ever leaves the
    process, because ocr_engine.session.post is intercepted.
    """
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "test-key-not-used")
    monkeypatch.setattr(settings, "OLLAMA_API_KEY", "test-key-not-used")


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


class _Resp:
    def __init__(self, status: int, payload: dict) -> None:
        self.status_code = status
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self) -> dict:
        return self._payload


def _ok() -> _Resp:
    content = json.dumps({"fields": {"Komponist": "Bach", "Signatur": "Spez. 1"}})
    return _Resp(200, {"choices": [{"message": {"content": content}}]})


def _payment_required() -> _Resp:
    # OpenRouter's real refusal, as observed in production.
    return _Resp(402, {"error": {"message": (
        "This request's maximum cost exceeds your available credits. "
        "Add credits, or lower max_tokens or prompt size."
    )}})


@pytest.fixture
def transport(monkeypatch):
    """Record every outbound request the engine makes, and answer it locally."""
    posts: list = []

    def fake_post(url, headers=None, json=None, **kw):
        posts.append({"url": url, "model": (json or {}).get("model")})
        return _ok()

    monkeypatch.setattr(ocr_engine.session, "post", fake_post)
    return posts


@pytest.fixture
def failing_transport(monkeypatch):
    """Succeed once, then refuse with HTTP 402 — the production failure shape.

    Each call sleeps briefly. A real VLM request takes seconds, which is what
    gives cooperative cancellation time to take effect; an instant mock would
    drain the whole queue before the stop could be observed and would therefore
    test nothing about stopping.
    """
    posts: list = []

    def fake_post(url, headers=None, json=None, **kw):
        posts.append({"url": url, "model": (json or {}).get("model")})
        time.sleep(0.02)
        return _ok() if len(posts) <= 1 else _payment_required()

    monkeypatch.setattr(ocr_engine.session, "post", fake_post)
    return posts


@pytest.fixture
def import_root(tmp_path, monkeypatch):
    root = tmp_path / "amiga"
    folder = root / "Batch_001"
    folder.mkdir(parents=True)
    for i in range(CARDS):
        (folder / f"IMG_{i:03d}.JPG").write_bytes(JPEG)
    monkeypatch.setattr(settings, "BULK_IMPORT_ROOT", str(root))
    return root


@pytest.fixture
def template():
    from app.models.schemas import TemplateCreate

    tpl = template_service.create_template(TemplateCreate(name="Routing probe", fields=FIELDS))
    yield tpl
    template_service.delete_template(tpl.id)


@pytest.fixture
def runs_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(bulk_manager, "runs_dir", tmp_path / "bulk_runs")
    return bulk_manager.runs_dir


def _bulk_batch(provider="ollama", model=OLLAMA_MODEL, count=2):
    """A batch materialised the way bulk does it: no provider in its config."""
    root = settings.BULK_IMPORT_ROOT
    imported = bulk_import.materialise_folder("Batch_001", fields=FIELDS)
    return imported["batch_name"], root, model, provider


def _interactive_batch(provider, model=None, count=2):
    """A batch started the interactive way: provider persisted in config.json."""
    sid = batch_manager.generate_session_id()
    session = batch_manager.get_temp_session_path(sid)
    for i in range(count):
        (session / f"card_{i}.jpg").write_bytes(JPEG)
    name = batch_manager.create_batch(custom_name="interactive", session_id=sid, fields=FIELDS)
    path = batch_manager.get_batch_path(name) / "config.json"
    config = json.loads(path.read_text())
    config["provider"] = provider
    if model:
        config["model"] = model
    path.write_text(json.dumps(config))
    return name


def _urls(posts):
    return {p["url"] for p in posts}


def _models(posts):
    return {p["model"] for p in posts}


# --------------------------------------------------------------------------- #
# A + C — bulk Ollama routing and model propagation
# --------------------------------------------------------------------------- #
def test_bulk_ollama_run_calls_the_ollama_endpoint(import_root, transport):
    """Case A: the frozen provider decides the endpoint, not a default."""
    batch, *_ = _bulk_batch()
    asyncio.run(run_ocr_task(batch, resume=True, progress_callback=lambda n, p: None,
                             provider="ollama", model=OLLAMA_MODEL))

    assert _urls(transport) == {settings.OLLAMA_API_ENDPOINT}
    assert settings.API_ENDPOINT not in _urls(transport)
    assert transport, "the engine must actually have been called"


def test_bulk_ollama_run_makes_zero_openrouter_calls(import_root, transport):
    """Case A: the regression that mattered — no request may reach OpenRouter."""
    batch, *_ = _bulk_batch()
    asyncio.run(run_ocr_task(batch, resume=True, progress_callback=lambda n, p: None,
                             provider="ollama", model=OLLAMA_MODEL))

    openrouter_host = provider_endpoint_host("openrouter")
    assert openrouter_host and openrouter_host not in " ".join(_urls(transport))


def test_frozen_model_reaches_the_request_verbatim(import_root, transport):
    """Case C: qwen3-vl:235b must not be substituted by the provider default."""
    batch, *_ = _bulk_batch()
    asyncio.run(run_ocr_task(batch, resume=True, progress_callback=lambda n, p: None,
                             provider="ollama", model=OLLAMA_MODEL))

    assert _models(transport) == {OLLAMA_MODEL}
    assert settings.MODEL_NAME not in _models(transport)


def test_explicit_provider_overrides_the_batch_config(import_root, transport):
    """A stale provider left in config.json must not win over the run's own."""
    batch, *_ = _bulk_batch()
    path = batch_manager.get_batch_path(batch) / "config.json"
    config = json.loads(path.read_text())
    config["provider"] = "openrouter"          # e.g. an earlier interactive start
    config["model"] = "some/other-model"
    path.write_text(json.dumps(config))

    asyncio.run(run_ocr_task(batch, resume=True, progress_callback=lambda n, p: None,
                             provider="ollama", model=OLLAMA_MODEL))

    assert _urls(transport) == {settings.OLLAMA_API_ENDPOINT}
    assert _models(transport) == {OLLAMA_MODEL}


# --------------------------------------------------------------------------- #
# B — bulk OpenRouter routing still works
# --------------------------------------------------------------------------- #
def test_bulk_openrouter_run_calls_the_openrouter_endpoint(import_root, transport):
    """Case B: an operator who chooses the paid provider still gets it."""
    batch, *_ = _bulk_batch()
    asyncio.run(run_ocr_task(batch, resume=True, progress_callback=lambda n, p: None,
                             provider="openrouter", model=None))

    assert _urls(transport) == {settings.API_ENDPOINT}
    assert _models(transport) == {settings.MODEL_NAME}


# --------------------------------------------------------------------------- #
# D — fail closed
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("provider", [None, "", "   ", "openai", "litellm", "OpenRouter "])
def test_resolve_provider_never_guesses(provider):
    """An absent or unknown provider is a configuration fault, not a default.

    "OpenRouter " with different casing/whitespace is accepted (normalised);
    everything unrecognised raises. The old code returned OpenRouter for all of
    these.
    """
    if provider and provider.strip().lower() in ("ollama", "openrouter"):
        endpoint, _model, _key = _resolve_provider(provider)
        assert endpoint == settings.API_ENDPOINT
        return
    with pytest.raises(ProviderConfigurationError):
        _resolve_provider(provider)


def test_missing_provider_makes_no_http_request(import_root, transport):
    """Case D: fail closed *before* any card is sent anywhere."""
    batch, *_ = _bulk_batch()   # bulk batch: no provider in config.json
    asyncio.run(run_ocr_task(batch, resume=True, progress_callback=lambda n, p: None))

    assert transport == [], "a missing provider must not produce a single request"


def test_missing_provider_does_not_silently_become_openrouter(import_root, transport):
    """The exact old behaviour, now asserted as forbidden."""
    batch, *_ = _bulk_batch()
    asyncio.run(run_ocr_task(batch, resume=True, progress_callback=lambda n, p: None))

    assert settings.API_ENDPOINT not in _urls(transport)
    assert settings.OLLAMA_API_ENDPOINT not in _urls(transport), "nor Ollama — no guessing"


def test_missing_provider_reports_a_clear_configuration_error(import_root, transport):
    """The operator must be told what is wrong, not left with silent failures."""
    from app.services.ws_manager import ws_manager

    batch, *_ = _bulk_batch()
    asyncio.run(run_ocr_task(batch, resume=True, progress_callback=lambda n, p: None))

    state = ws_manager.batch_states.get(batch)
    assert state is not None and state.status == "failed"
    assert "provider" in (state.error or "").lower()


# --------------------------------------------------------------------------- #
# E — interactive path unchanged
# --------------------------------------------------------------------------- #
def test_interactive_batch_routes_from_its_config(transport):
    """Case E: the persisted provider still drives routing with no arguments."""
    batch = _interactive_batch("ollama", OLLAMA_MODEL)
    asyncio.run(run_ocr_task(batch, resume=True, progress_callback=lambda n, p: None))

    assert _urls(transport) == {settings.OLLAMA_API_ENDPOINT}
    assert _models(transport) == {OLLAMA_MODEL}


def test_interactive_openrouter_batch_still_works(transport):
    """Case E: nothing about the paid interactive path changes."""
    batch = _interactive_batch("openrouter")
    asyncio.run(run_ocr_task(batch, resume=True, progress_callback=lambda n, p: None))

    assert _urls(transport) == {settings.API_ENDPOINT}


# --------------------------------------------------------------------------- #
# F — retry / resume
# --------------------------------------------------------------------------- #
def test_retry_of_a_bulk_batch_cannot_reach_openrouter(import_root, transport):
    """Case F: the retry endpoints call run_ocr_task without a provider.

    For a bulk-created batch there is nothing in config.json to fall back to, so
    the old default would have sent the retries to OpenRouter.
    """
    batch, *_ = _bulk_batch()
    asyncio.run(run_ocr_task(batch, resume=False, retry_errors=True,
                             progress_callback=lambda n, p: None))

    assert settings.API_ENDPOINT not in _urls(transport)
    assert transport == []


def test_resume_of_a_bulk_batch_keeps_the_frozen_provider(import_root, transport):
    """Case F: a resumed folder must route exactly as the first attempt did."""
    batch, *_ = _bulk_batch()
    asyncio.run(run_ocr_task(batch, resume=True, progress_callback=lambda n, p: None,
                             provider="ollama", model=OLLAMA_MODEL))
    first = len(transport)
    assert first > 0

    # Resuming sends nothing again (every card already succeeded) and still
    # never targets the paid endpoint.
    asyncio.run(run_ocr_task(batch, resume=True, progress_callback=lambda n, p: None,
                             provider="ollama", model=OLLAMA_MODEL))
    assert len(transport) == first, "completed cards must not be re-sent"
    assert _urls(transport) == {settings.OLLAMA_API_ENDPOINT}


# --------------------------------------------------------------------------- #
# G — HTTP 402 stops the run
# --------------------------------------------------------------------------- #
def test_http_402_stops_the_bulk_run_as_a_structural_failure(
    import_root, runs_dir, template, failing_transport
):
    """Case G: a billing refusal must not be retried against 500 more cards."""
    run = bulk_manager.create_run(
        name="AMIGA", template_id=template.id, schema_fields=FIELDS,
        provider="ollama", model=OLLAMA_MODEL,
        folders=[{"source_folder": "Batch_001", "images_total": CARDS}],
    )

    async def go():
        await bulk_orchestrator.start_run(run["bulk_run_id"])
        task = bulk_orchestrator._tasks.get(run["bulk_run_id"])
        if task:
            await task

    asyncio.run(go())

    final = bulk_manager.get_run(run["bulk_run_id"])
    assert final["status"] == STATUS_FAILED
    assert "refused" in (final.get("error") or "").lower()

    # The point of the fix: it stopped rather than sending every remaining card.
    # Cards already in flight (up to MAX_WORKERS) still finish, so the bound is
    # "clearly fewer than all", not an exact count.
    assert len(failing_transport) < CARDS, (
        f"the run kept sending after the 402 ({len(failing_transport)} of {CARDS} cards)"
    )


def test_http_402_error_reaches_the_card_row(import_root, failing_transport):
    """The provider's message is preserved for the operator, verbatim."""
    batch, *_ = _bulk_batch()
    asyncio.run(run_ocr_task(batch, resume=True, progress_callback=lambda n, p: None,
                             provider="ollama", model=OLLAMA_MODEL))

    results, _ = read_checkpoint(batch_manager.get_batch_path(batch) / "checkpoint.json")
    failed = [r for r in results if r.get("success") is not True]
    assert failed, "the 402 must be recorded, not swallowed"
    assert "402" in str(failed[0].get("error"))


@pytest.mark.parametrize(
    "error,expected",
    [
        ("HTTP 402: This request's maximum cost exceeds your available credits.", True),
        ("HTTP 402", True),
        ("Insufficient credits for this request", True),
        ("Add credits, or lower max_tokens", True),
        ("HTTP 401: invalid api key", True),
        ("HTTP 500: upstream unavailable", False),
        ("JSON-Parsing fehlgeschlagen", False),
        ("Karte 402 unlesbar", False),   # a bare 402 in card text must not abort
        (None, False),
        ("", False),
    ],
)
def test_provider_fault_classification(error, expected):
    """Credential *and* billing refusals stop a run; ordinary card errors do not."""
    assert bulk_orchestrator._provider_fault(error) is expected


# --------------------------------------------------------------------------- #
# H — corrector stays off for bulk
# --------------------------------------------------------------------------- #
def test_bulk_batches_have_the_corrector_disabled(import_root):
    """Case H: bulk has no corrector control, so it must not enable one."""
    batch, *_ = _bulk_batch()
    config = json.loads((batch_manager.get_batch_path(batch) / "config.json").read_text())

    assert config.get("corrector_enabled") is False
    assert config.get("field_rules") is None


def test_bulk_run_never_calls_the_corrector_model(import_root, transport):
    """The corrector would target OpenRouter even on an Ollama run — prove it is silent."""
    batch, *_ = _bulk_batch()
    asyncio.run(run_ocr_task(batch, resume=True, progress_callback=lambda n, p: None,
                             provider="ollama", model=OLLAMA_MODEL))

    assert settings.CORRECTOR_MODEL_NAME not in _models(transport)
    assert _urls(transport) == {settings.OLLAMA_API_ENDPOINT}


# --------------------------------------------------------------------------- #
# Audit accuracy
# --------------------------------------------------------------------------- #
def test_provider_host_is_a_bare_host():
    """The audit records a host, never a URL that could carry a credential."""
    for provider in ("ollama", "openrouter"):
        host = provider_endpoint_host(provider)
        assert host and "/" not in host and "?" not in host
        assert not host.startswith("http")
    assert provider_endpoint_host(None) == ""


def test_provider_hosts_are_distinguishable():
    """The whole point: the audit trail can tell local from remote apart."""
    assert provider_endpoint_host("ollama") != provider_endpoint_host("openrouter")
