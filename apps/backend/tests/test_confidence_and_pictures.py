"""Tests for confidence scoring + picture description (v1.1 features)."""
import json

from app.services.ocr_engine import ocr_engine
from app.services.batch_manager import batch_manager


# --------------------------------------------------------------------------- #
# _split_extraction — defensive parsing of the wrapped/legacy response shapes
# --------------------------------------------------------------------------- #
def test_split_wrapped_shape():
    parsed = {
        "fields": {"Komponist": "Bach", "Signatur": "S1"},
        "confidence": {"Komponist": 0.9, "Signatur": 0.4},
        "confidence_overall": 0.7,
    }
    fields, conf, overall = ocr_engine._split_extraction(parsed)
    assert fields == {"Komponist": "Bach", "Signatur": "S1"}
    assert conf == {"Komponist": 0.9, "Signatur": 0.4}
    assert overall == 0.7


def test_split_legacy_flat_shape():
    """A model that ignores the contract returns a flat dict → fields only, no crash."""
    fields, conf, overall = ocr_engine._split_extraction({"Komponist": "Bach"})
    assert fields == {"Komponist": "Bach"}
    assert conf == {}
    assert overall is None


def test_split_sanitizes_confidence():
    parsed = {
        "fields": {"A": "x"},
        "confidence": {"A": 1.7, "Ghost": 0.5, "B": "high"},  # clamp / drop-unknown / drop-nonnumeric
        "confidence_overall": "bad",
    }
    fields, conf, overall = ocr_engine._split_extraction(parsed)
    assert conf == {"A": 1.0}            # clamped to [0,1]; Ghost not in fields; B non-numeric
    assert overall is None               # "bad" → None


def test_split_non_dict_input():
    fields, conf, overall = ocr_engine._split_extraction("not json")
    assert fields == {} and conf == {} and overall is None


# --------------------------------------------------------------------------- #
# Prompt includes the confidence contract + optional picture instruction
# --------------------------------------------------------------------------- #
def test_prompt_has_confidence_contract():
    p = ocr_engine._generate_prompt(["Komponist"], describe_pictures=False)
    assert "confidence_overall" in p
    assert "Bildbeschreibung" not in p


def test_prompt_has_picture_instruction_when_enabled():
    p = ocr_engine._generate_prompt(["Komponist"], describe_pictures=True)
    assert "Bildbeschreibung" in p


# --------------------------------------------------------------------------- #
# describe_pictures round-trips through create_batch → config.json
# --------------------------------------------------------------------------- #
def test_describe_pictures_persisted(tmp_path, monkeypatch):
    # Point batch_manager at a temp session with one file, then create a batch.
    sid = batch_manager.generate_session_id()
    session_dir = batch_manager.get_temp_session_path(sid)
    (session_dir / "card.jpg").write_bytes(b"\xff\xd8\xff\xe0stub\xff\xd9")

    batch_name = batch_manager.create_batch(
        custom_name="conf test",
        session_id=sid,
        fields=["Komponist"],
        describe_pictures=True,
    )
    config = json.loads((batch_manager.get_batch_path(batch_name) / "config.json").read_text())
    assert config["describe_pictures"] is True

    # Cleanup
    batch_manager.delete_batch(batch_name)


# --------------------------------------------------------------------------- #
# End-to-end result assembly with a mocked VLM (deterministic; no network)
# --------------------------------------------------------------------------- #
def test_process_card_attaches_confidence_and_picture(monkeypatch, tmp_path):
    """_process_card_sync must surface confidence + confidence_overall and pass a
    model-supplied Bildbeschreibung through into data."""
    img = tmp_path / "card.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0stub\xff\xd9")

    wrapped = {
        "fields": {"Komponist": "Bach", "Bildbeschreibung": "Ein Porträt eines Mannes."},
        "confidence": {"Komponist": 0.92, "Bildbeschreibung": 0.5},
        "confidence_overall": 0.8,
    }
    # Bypass the network: return the parsed object directly.
    monkeypatch.setattr(ocr_engine, "_call_vlm_api_resilient", lambda *a, **k: (wrapped, None))

    res = ocr_engine._process_card_sync(
        img, "batchX", fields=["Komponist", "Bildbeschreibung"], describe_pictures=True
    )
    assert res["success"] is True
    assert res["confidence"] == {"Komponist": 0.92, "Bildbeschreibung": 0.5}
    assert res["confidence_overall"] == 0.8
    assert res["data"]["Bildbeschreibung"] == "Ein Porträt eines Mannes."


def test_process_card_legacy_shape_no_confidence(monkeypatch, tmp_path):
    """A flat legacy response still succeeds, with confidence null (backwards compat)."""
    img = tmp_path / "card.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0stub\xff\xd9")
    monkeypatch.setattr(ocr_engine, "_call_vlm_api_resilient", lambda *a, **k: ({"Komponist": "Bach"}, None))

    res = ocr_engine._process_card_sync(img, "batchX", fields=["Komponist"])
    assert res["success"] is True
    assert res["confidence"] is None
    assert res["confidence_overall"] is None
    assert res["data"]["Komponist"] == "Bach"
