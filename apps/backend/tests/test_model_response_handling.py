"""How one VLM response is classified, and what that costs in requests.

Every failure in the observed AMIGA bulk test arrived as the same message —
"JSON-Parsing fehlgeschlagen" — whether the model had returned nothing at all,
had been cut off mid-object by the output limit, or had produced complete but
invalid JSON. Those are three different faults with three different remedies,
so they are asserted separately here.

The checkpoint of that run also showed six different cards failing at
104.2–104.4 s, i.e. at an identical generated-token count: the hard-coded
``max_tokens=4096`` was the binding limit, and a reasoning-capable VLM spends
that budget on chain-of-thought before it emits any JSON. Hence the assertions
that the limit is configurable and that a limit-caused failure is never retried.

Nothing here touches a provider: ``ocr_engine.session.post`` is intercepted,
which is the engine's only outbound call.
"""
import json
import threading
import time

import pytest
import requests

from app.core.config import settings
from app.core.checkpoint import read_checkpoint
from app.services import ocr_engine as engine_module
from app.services.batch_manager import batch_manager
from app.services.ocr_engine import (
    ERROR_EMPTY_RESPONSE,
    ERROR_INVALID_JSON,
    ERROR_NO_CHOICES,
    ERROR_TRUNCATED_RESPONSE,
    ocr_engine,
)

# Captured before any test stubs out time.sleep: the two concurrency tests need a
# real overlap window, everything else needs no waiting at all.
_REAL_SLEEP = time.sleep

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16 + b"\xff\xd9"
FIELDS = ["Komponist", "Signatur"]

TRACKS = {
    "description": "Einzeltitel",
    "max_items": 20,
    "fields": [{"name": "Lfd_Nr"}, {"name": "Titel"}, {"name": "Spieldauer"}],
}


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _fast_and_credentialed(monkeypatch):
    """Placeholder keys, and no real sleeping between attempts.

    The engine returns "API Key missing" before issuing a request when a key is
    empty, so without this these assertions would see zero requests on a machine
    with no keys configured. No request leaves the process — session.post is
    intercepted in every test.
    """
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "test-key-not-used")
    monkeypatch.setattr(settings, "OLLAMA_API_KEY", "test-key-not-used")
    monkeypatch.setattr(engine_module, "_MODEL_RETRY_DELAY_SECONDS", 0.0)
    monkeypatch.setattr(time, "sleep", lambda _s: None)


@pytest.fixture(autouse=True)
def _two_attempts(monkeypatch):
    """MAX_RETRIES=2 — the operator's current setting, made explicit.

    Its documented meaning is "requests in total": an initial request plus at
    most one retry, never a fresh budget per fault class.
    """
    monkeypatch.setattr(settings, "MAX_RETRIES", 2)


@pytest.fixture(autouse=True)
def _clean_batches():
    before = set(batch_manager.list_batches())
    yield
    for name in set(batch_manager.list_batches()) - before:
        try:
            batch_manager.release_batch_lock(name)
            batch_manager.delete_batch(name)
        except Exception:
            pass


class _Resp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload or {}
        self.text = json.dumps(self._payload)
        self.headers: dict = {}

    def json(self):
        return self._payload


def _choice(content, finish_reason="stop", **extra):
    message = {"content": content}
    message.update(extra)
    return _Resp(200, {"choices": [{"message": message, "finish_reason": finish_reason}]})


def _valid_payload(tracks=None):
    fields = {"Komponist": "Bach", "Signatur": "Spez. 1"}
    if tracks is not None:
        fields["Titel_Tracks"] = tracks
    return json.dumps({"fields": fields, "confidence_overall": 0.9})


@pytest.fixture
def transport(monkeypatch):
    """Programmable transport. Set ``.responses`` to a list, or ``.always``."""

    class Recorder:
        def __init__(self):
            self.posts: list = []
            self.responses: list = []
            self.always = _choice(_valid_payload())

        def __call__(self, url, headers=None, json=None, **kw):
            self.posts.append({"url": url, "payload": json or {}, "timeout": kw.get("timeout")})
            if self.responses:
                nxt = self.responses.pop(0)
                return nxt() if callable(nxt) else nxt
            return self.always() if callable(self.always) else self.always

    recorder = Recorder()
    monkeypatch.setattr(ocr_engine.session, "post", recorder)
    return recorder


@pytest.fixture
def card(tmp_path):
    path = tmp_path / "IMG_001.JPG"
    path.write_bytes(JPEG)
    return path


def _call(card, **kw):
    return ocr_engine._call_vlm_api_resilient(
        card, fields=FIELDS, api_endpoint=settings.OLLAMA_API_ENDPOINT,
        model_name="qwen3-vl:32b", api_key="test-key-not-used", **kw
    )


# --------------------------------------------------------------------------- #
# 7 — a valid response
# --------------------------------------------------------------------------- #
def test_valid_json_response_is_parsed_in_one_request(card, transport):
    parsed, error = _call(card)

    assert error is None
    assert parsed["fields"]["Komponist"] == "Bach"
    assert len(transport.posts) == 1, "a good answer must not be retried"


def test_response_close_to_the_output_limit_still_succeeds(card, transport):
    """A long but complete answer is not a failure — only a truncated one is."""
    tracks = [{"Lfd_Nr": str(i), "Titel": "T" * 60, "Spieldauer": "3:45"} for i in range(20)]
    transport.always = _choice(_valid_payload(tracks), finish_reason="stop")

    parsed, error = _call(card)

    assert error is None
    assert len(parsed["fields"]["Titel_Tracks"]) == 20


# --------------------------------------------------------------------------- #
# 8 + 16 — empty HTTP 200
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("content", ["", "   ", None])
def test_empty_http_200_is_its_own_error_class(card, transport, content):
    """The case that produced 'JSON-Parsing fehlgeschlagen. Antwort:' with
    nothing after the colon, because json.loads("") was reached."""
    transport.always = _choice(content, finish_reason="stop")

    _parsed, error = _call(card)

    assert ERROR_EMPTY_RESPONSE in error
    assert "JSON-Parsing fehlgeschlagen" not in error


def test_empty_response_reports_the_reasoning_size_not_its_text(card, transport):
    """A thinking model's chain-of-thought explains the empty content, but it is
    model output about a card — only its length may surface."""
    secret = "Die Karte nennt Bestellnummer 56 491 und Tonband 12116-02"
    transport.always = _choice("", finish_reason="stop", reasoning=secret)

    _parsed, error = _call(card)

    assert str(len(secret)) in error
    assert "56 491" not in error and secret not in error


def test_unexplained_empty_response_gets_exactly_one_retry(card, transport):
    """Retryable, but inside the MAX_RETRIES budget — 2 requests, not 3."""
    transport.always = _choice("", finish_reason="stop")

    _parsed, error = _call(card)

    assert len(transport.posts) == 2
    assert ERROR_EMPTY_RESPONSE in error


def test_empty_response_that_succeeds_on_retry_is_not_a_failure(card, transport):
    transport.responses = [_choice(""), _choice(_valid_payload())]

    parsed, error = _call(card)

    assert error is None and parsed["fields"]["Komponist"] == "Bach"
    assert len(transport.posts) == 2


def test_empty_response_caused_by_the_output_limit_is_not_retried(card, transport):
    """finish_reason=length means the budget was spent before any content. An
    identical second request hits the identical limit, so it is pure cost."""
    transport.always = _choice("", finish_reason="length", reasoning="x" * 9000)

    _parsed, error = _call(card)

    assert len(transport.posts) == 1, "a limit-caused failure must not be retried"
    assert ERROR_EMPTY_RESPONSE in error
    assert "VLM_MAX_OUTPUT_TOKENS" in error, "the operator must be told the remedy"


# --------------------------------------------------------------------------- #
# 9 + 10 — finish_reason=length
# --------------------------------------------------------------------------- #
def test_truncated_json_is_reported_as_truncated_not_as_invalid(card, transport):
    """The observed FALL A: the answer starts as plausible JSON and stops."""
    cut = '{\n  "fields": {\n    "Bestellnummer": "56 491",\n    "Tonband_Nr": "12116'
    transport.always = _choice(cut, finish_reason="length")

    _parsed, error = _call(card)

    assert ERROR_TRUNCATED_RESPONSE in error
    assert ERROR_INVALID_JSON not in error
    assert "VLM_MAX_OUTPUT_TOKENS" in error


def test_truncation_is_detected_even_when_the_fragment_happens_to_parse(card, transport):
    """_extract_json_from_model_content trims to the last closing brace, so a
    cut-off answer can parse and still be an incomplete record. finish_reason
    is the only reliable signal, which is why it is now read."""
    cut = '{"fields": {"Komponist": "Bach"}, "confidence": {"Komponist": 0.9'
    transport.always = _choice(cut, finish_reason="length")

    parsed, error = _call(card)

    assert parsed is None
    assert ERROR_TRUNCATED_RESPONSE in error


def test_truncated_response_is_never_retried(card, transport):
    transport.always = _choice('{"fields": {"Komponist": "Ba', finish_reason="length")

    _call(card)

    assert len(transport.posts) == 1


# --------------------------------------------------------------------------- #
# 11 + 12 + 15 — invalid and schema-invalid JSON
# --------------------------------------------------------------------------- #
def test_complete_but_invalid_json_is_its_own_error_class(card, transport):
    transport.always = _choice('{"fields": {"Komponist": "Bach",,}}', finish_reason="stop")

    _parsed, error = _call(card)

    assert ERROR_INVALID_JSON in error
    assert ERROR_TRUNCATED_RESPONSE not in error


def test_invalid_json_keeps_a_bounded_preview_for_the_curator(card, transport):
    transport.always = _choice("Ich kann diese Karte nicht lesen." * 40, finish_reason="stop")

    _parsed, error = _call(card)

    assert ERROR_INVALID_JSON in error
    assert len(error) < 500, "the preview must stay bounded"


def test_json_that_is_neither_object_nor_list_is_invalid(card, transport):
    """json.loads("42") succeeds and would have produced an empty record."""
    transport.always = _choice("42", finish_reason="stop")

    parsed, error = _call(card)

    assert parsed is None
    assert ERROR_INVALID_JSON in error


def test_invalid_json_gets_exactly_one_retry(card, transport):
    transport.always = _choice("nope", finish_reason="stop")

    _call(card)

    assert len(transport.posts) == 2


def test_invalid_json_that_succeeds_on_retry_is_not_a_failure(card, transport):
    transport.responses = [_choice("nope"), _choice(_valid_payload())]

    parsed, error = _call(card)

    assert error is None and parsed is not None
    assert len(transport.posts) == 2


def test_missing_choices_is_reported_with_the_providers_own_message(card, transport):
    transport.always = _Resp(200, {"choices": [], "error": {"message": "model not loaded"}})

    _parsed, error = _call(card)

    assert ERROR_NO_CHOICES in error
    assert "model not loaded" in error


def test_a_malformed_envelope_does_not_raise_a_python_error(card, transport):
    """A missing `message` used to become a bare KeyError in the card row."""
    transport.always = _Resp(200, {"choices": [{"finish_reason": "stop"}]})

    _parsed, error = _call(card)

    assert ERROR_EMPTY_RESPONSE in error
    assert "KeyError" not in error and "NoneType" not in error


# --------------------------------------------------------------------------- #
# 17 + 18 — provider faults keep their existing retry policy
# --------------------------------------------------------------------------- #
def test_http_402_is_not_retried(card, transport):
    """A billing refusal applies to every remaining card; retrying it is a storm."""
    transport.always = _Resp(402, {"error": {"message": "Add credits, or lower max_tokens"}})

    _parsed, error = _call(card)

    assert len(transport.posts) == 1
    assert "402" in error


def test_timeout_retries_are_bounded_by_max_retries(card, transport, monkeypatch):
    def timing_out(*a, **kw):
        transport.posts.append({"url": "", "payload": {}, "timeout": None})
        raise requests.exceptions.Timeout()

    monkeypatch.setattr(ocr_engine.session, "post", timing_out)

    _parsed, error = _call(card)

    assert len(transport.posts) == settings.MAX_RETRIES == 2
    assert "Max. Versuche" in error


def test_http_500_retries_are_bounded_by_max_retries(card, transport):
    transport.always = _Resp(500, {"error": {"message": "upstream unavailable"}})

    _call(card)

    assert len(transport.posts) == settings.MAX_RETRIES


# --------------------------------------------------------------------------- #
# Output limit and JSON mode are configuration, not constants
# --------------------------------------------------------------------------- #
def test_output_limit_comes_from_configuration(card, transport, monkeypatch):
    monkeypatch.setattr(settings, "VLM_MAX_OUTPUT_TOKENS", 12345)

    _call(card)

    assert transport.posts[0]["payload"]["max_tokens"] == 12345


def test_default_output_limit_is_above_the_limit_that_truncated_the_amiga_run():
    """4096 was the binding cause of every failure in the observed run."""
    assert settings.VLM_MAX_OUTPUT_TOKENS >= 8192


def test_request_timeout_reaches_the_transport(card, transport, monkeypatch):
    monkeypatch.setattr(settings, "VLM_REQUEST_TIMEOUT_SECONDS", 900)

    _call(card)

    assert transport.posts[0]["timeout"] == 900


def test_json_mode_is_off_by_default(card, transport):
    _call(card)

    assert "response_format" not in transport.posts[0]["payload"]


def test_json_mode_adds_response_format_when_enabled(card, transport, monkeypatch):
    monkeypatch.setattr(settings, "VLM_JSON_MODE", True)

    _call(card)

    assert transport.posts[0]["payload"]["response_format"] == {"type": "json_object"}


# --------------------------------------------------------------------------- #
# 13 — repeatable groups survive the new response path
# --------------------------------------------------------------------------- #
def test_repeatable_group_with_several_tracks_is_preserved(tmp_path, transport):
    tracks = [
        {"Lfd_Nr": "1", "Titel": "Rhapsody in Blue", "Spieldauer": "13:20"},
        {"Lfd_Nr": "2", "Titel": "Summertime", "Spieldauer": "3:05"},
        {"Lfd_Nr": "3", "Titel": "I Got Rhythm", "Spieldauer": "2:41"},
    ]
    transport.always = _choice(_valid_payload(tracks), finish_reason="stop")
    card_path = tmp_path / "IMG_002.JPG"
    card_path.write_bytes(JPEG)

    result = ocr_engine._process_card_sync(
        card_path, "batch", FIELDS + ["Titel_Tracks"],
        api_endpoint=settings.OLLAMA_API_ENDPOINT, model_name="qwen3-vl:32b",
        api_key="test-key-not-used", field_groups={"Titel_Tracks": TRACKS},
    )

    assert result["success"] is True
    stored = json.loads(result["data"]["Titel_Tracks"])
    assert [item["Titel"] for item in stored] == [t["Titel"] for t in tracks]
    assert result["validation"]["Titel_Tracks"]["status"] == "valid"


def test_a_truncated_group_response_fails_the_card_without_a_phantom_group(tmp_path, transport):
    """A card cut off inside the track array must be a recorded failure, not a
    silent success with half a tracklist."""
    transport.always = _choice(
        '{"fields": {"Titel_Tracks": [{"Lfd_Nr": "1", "Titel": "Rhaps',
        finish_reason="length",
    )
    card_path = tmp_path / "IMG_003.JPG"
    card_path.write_bytes(JPEG)

    result = ocr_engine._process_card_sync(
        card_path, "batch", FIELDS + ["Titel_Tracks"],
        api_endpoint=settings.OLLAMA_API_ENDPOINT, model_name="qwen3-vl:32b",
        api_key="test-key-not-used", field_groups={"Titel_Tracks": TRACKS},
    )

    assert result["success"] is False
    assert ERROR_TRUNCATED_RESPONSE in result["error"]
    assert result.get("data") is None


# --------------------------------------------------------------------------- #
# 4 — MAX_WORKERS=1 means one inference at a time
# --------------------------------------------------------------------------- #
def test_max_workers_one_allows_only_one_concurrent_inference(tmp_path, monkeypatch):
    """The operator's setting must actually bound provider concurrency."""
    import asyncio

    monkeypatch.setattr(settings, "MAX_WORKERS", 1)
    monkeypatch.setattr(settings, "OLLAMA_API_KEY", "test-key-not-used")

    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()
    for i in range(6):
        (batch_dir / f"IMG_{i:03d}.JPG").write_bytes(JPEG)

    in_flight = 0
    peak = 0
    guard = threading.Lock()

    def fake_post(url, headers=None, json=None, **kw):
        nonlocal in_flight, peak
        with guard:
            in_flight += 1
            peak = max(peak, in_flight)
        _REAL_SLEEP(0.01)
        with guard:
            in_flight -= 1
        return _choice(_valid_payload())

    monkeypatch.setattr(ocr_engine.session, "post", fake_post)

    asyncio.run(
        ocr_engine.process_batch(
            batch_dir=batch_dir, fields=FIELDS,
            api_endpoint=settings.OLLAMA_API_ENDPOINT, model_name="qwen3-vl:32b",
            api_key="test-key-not-used",
        )
    )

    assert peak == 1, f"MAX_WORKERS=1 must serialise inference, saw {peak} in flight"


def test_max_workers_above_one_still_parallelises(tmp_path, monkeypatch):
    """The bound is the setting, not a hard-coded 1 — the interactive path
    still runs a pool."""
    import asyncio

    monkeypatch.setattr(settings, "MAX_WORKERS", 4)

    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()
    for i in range(8):
        (batch_dir / f"IMG_{i:03d}.JPG").write_bytes(JPEG)

    in_flight = 0
    peak = 0
    guard = threading.Lock()

    def fake_post(url, headers=None, json=None, **kw):
        nonlocal in_flight, peak
        with guard:
            in_flight += 1
            peak = max(peak, in_flight)
        _REAL_SLEEP(0.05)
        with guard:
            in_flight -= 1
        return _choice(_valid_payload())

    monkeypatch.setattr(ocr_engine.session, "post", fake_post)

    asyncio.run(
        ocr_engine.process_batch(
            batch_dir=batch_dir, fields=FIELDS,
            api_endpoint=settings.OLLAMA_API_ENDPOINT, model_name="qwen3-vl:32b",
            api_key="test-key-not-used",
        )
    )

    assert 1 < peak <= 4


# --------------------------------------------------------------------------- #
# A failed card is recorded with its class, so the failure CSV is diagnostic
# --------------------------------------------------------------------------- #
def test_the_error_class_reaches_the_checkpoint_row(tmp_path, transport, monkeypatch):
    import asyncio

    monkeypatch.setattr(settings, "MAX_WORKERS", 1)
    transport.always = _choice("", finish_reason="length")

    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()
    (batch_dir / "IMG_001.JPG").write_bytes(JPEG)

    asyncio.run(
        ocr_engine.process_batch(
            batch_dir=batch_dir, fields=FIELDS,
            api_endpoint=settings.OLLAMA_API_ENDPOINT, model_name="qwen3-vl:32b",
            api_key="test-key-not-used",
        )
    )

    results, _ = read_checkpoint(batch_dir / "checkpoint.json")
    assert len(results) == 1
    assert ERROR_EMPTY_RESPONSE in results[0]["error"]
