"""Repeatable field groups: schema, canonical wire format, defensive normalisation.

All VLM calls are mocked; no network access.
"""
import json

import pytest

from app.models.schemas import FieldGroup, GroupChild, ResultPatch, Template
from app.services.validation import groups as G

TRACKS = FieldGroup(
    description="Einzeltitel mit je zugehöriger Spieldauer.",
    max_items=20,
    fields=[GroupChild(name="Lfd_Nr"), GroupChild(name="Titel"), GroupChild(name="Spieldauer")],
)


# --------------------------------------------------------------------------- #
# Schema: additive and backwards compatible
# --------------------------------------------------------------------------- #
def test_template_without_field_groups_still_loads():
    """Case 2: existing sparse templates must keep working untouched."""
    t = Template(id="x", name="Legacy", fields=["Komponist", "Signatur"])
    assert t.field_groups is None


def test_template_roundtrips_field_groups():
    t = Template(id="x", name="AMIGA", fields=["Gesamttitel", "Titel_Tracks"],
                 field_groups={"Titel_Tracks": TRACKS})
    again = Template(**json.loads(t.json()))
    assert again.field_groups is not None
    assert G.child_names(again.field_groups["Titel_Tracks"]) == ["Lfd_Nr", "Titel", "Spieldauer"]
    assert again.field_groups["Titel_Tracks"].max_items == 20


def test_generic_group_default_max_items_is_12():
    """Operator decision: 12 generic, 20 only for AMIGA."""
    g = FieldGroup(fields=[GroupChild(name="A")])
    assert g.max_items == 12


def test_result_patch_group_fields_are_optional():
    """Every existing scalar call site must stay valid."""
    p = ResultPatch(field="Komponist", value="Bach")
    assert p.group is None and p.index is None and p.group_op is None


# --------------------------------------------------------------------------- #
# Flattened keys (confidence + granular PATCH address)
# --------------------------------------------------------------------------- #
def test_child_key_roundtrip():
    key = G.child_key("Titel_Tracks", 2, "Spieldauer")
    assert key == "Titel_Tracks[2].Spieldauer"
    assert G.parse_child_key(key) == ("Titel_Tracks", 2, "Spieldauer")


@pytest.mark.parametrize("key", ["Komponist", "Titel_Tracks", "Titel_Tracks[].Titel",
                                 "Titel_Tracks[x].Titel", ""])
def test_parse_child_key_rejects_non_child_keys(key):
    assert G.parse_child_key(key) is None


# --------------------------------------------------------------------------- #
# Canonical serialisation
# --------------------------------------------------------------------------- #
def test_serialisation_is_canonical_and_stable():
    items = [{"Lfd_Nr": "1", "Titel": "The Man I Love", "Spieldauer": "3'21"}]
    once, twice = G.serialise_group(items), G.serialise_group(items)
    assert once == twice
    assert once == '[{"Lfd_Nr":"1","Titel":"The Man I Love","Spieldauer":"3\'21"}]'
    assert G.parse_group(once) == items


def test_serialisation_keeps_umlauts_readable():
    assert "Künstler" in G.serialise_group([{"Titel": "Künstler"}])


@pytest.mark.parametrize("raw,expected", [
    ("[]", []),
    ("", []),
    ("   ", []),
    (None, []),
    ("{not json", []),
    ('{"Titel":"X"}', [{"Titel": "X"}]),          # single object tolerated
    ('["nope"]', []),                              # non-object elements dropped
    ("42", []),
])
def test_parse_group_is_tolerant(raw, expected):
    assert G.parse_group(raw) == expected


# --------------------------------------------------------------------------- #
# normalise_group — the defensive core (plan §7)
# --------------------------------------------------------------------------- #
def test_zero_items_is_valid():
    """Case 3."""
    items, problems = G.normalise_group([], TRACKS)
    assert items == [] and problems == []
    assert G.outcome_for(problems)["status"] == "valid"


def test_absent_group_is_valid():
    items, problems = G.normalise_group(None, TRACKS)
    assert items == [] and problems == []


def test_one_item(   ):
    """Case 4."""
    items, problems = G.normalise_group(
        [{"Lfd_Nr": "1", "Titel": "The Man I Love", "Spieldauer": "3'21"}], TRACKS)
    assert items == [{"Lfd_Nr": "1", "Titel": "The Man I Love", "Spieldauer": "3'21"}]
    assert problems == []


def test_multiple_items_keep_document_order():
    """Case 5."""
    raw = [{"Lfd_Nr": "1", "Titel": "A"}, {"Lfd_Nr": "2", "Titel": "B"}, {"Lfd_Nr": "3", "Titel": "C"}]
    items, _ = G.normalise_group(raw, TRACKS)
    assert [i["Titel"] for i in items] == ["A", "B", "C"]


def test_missing_child_becomes_empty_not_absent():
    """Case 6: mixed complete/incomplete children."""
    items, _ = G.normalise_group([{"Titel": "A"}], TRACKS)
    assert items == [{"Lfd_Nr": "", "Titel": "A", "Spieldauer": ""}]


def test_missing_middle_duration_does_not_shift_later_values():
    """Case 7 — the central requirement.

    Title 1 -> 3'21, Title 2 -> (missing), Title 3 -> 4'06 must NOT collapse into
    two items where Title 2 inherits Title 3's duration.
    """
    raw = [
        {"Titel": "Title 1", "Spieldauer": "3'21"},
        {"Titel": "Title 2"},
        {"Titel": "Title 3", "Spieldauer": "4'06"},
    ]
    items, _ = G.normalise_group(raw, TRACKS)

    assert len(items) == 3
    assert [(i["Titel"], i["Spieldauer"]) for i in items] == [
        ("Title 1", "3'21"),
        ("Title 2", ""),        # ← empty, never 4'06
        ("Title 3", "4'06"),
    ]


def test_unknown_children_are_dropped_and_counted():
    """Case 9: a creative model must not widen the schema at runtime."""
    items, problems = G.normalise_group(
        [{"Titel": "A", "Erfundenes_Feld": "x", "NochEins": "y"}], TRACKS)
    assert set(items[0]) == {"Lfd_Nr", "Titel", "Spieldauer"}
    assert G.PROBLEM_UNKNOWN_CHILD in problems


def test_entirely_empty_item_is_dropped():
    items, _ = G.normalise_group([{"Titel": "A"}, {"Titel": "", "Spieldauer": ""}], TRACKS)
    assert len(items) == 1


@pytest.mark.parametrize("raw,code", [
    ("garbage",                       G.PROBLEM_MALFORMED),
    (42,                              G.PROBLEM_MALFORMED),
    (True,                            G.PROBLEM_MALFORMED),
    ({"Titel": "A"},                  G.PROBLEM_WAS_OBJECT),
    ('[{"Titel":"A"}]',               G.PROBLEM_WAS_STRING),
    (["not-an-object", {"Titel": "A"}], G.PROBLEM_NON_OBJECT_ITEM),
])
def test_malformed_output_is_handled_safely(raw, code):
    """Case 8: never raises, always yields a usable list plus a problem code."""
    items, problems = G.normalise_group(raw, TRACKS)
    assert isinstance(items, list)
    assert code in problems
    assert G.outcome_for(problems)["status"] == "invalid"
    assert G.outcome_for(problems)["rule_failed"] == G.GROUP_RULE


def test_problem_rationale_carries_no_card_content():
    """Diagnostics must not leak extracted content."""
    items, problems = G.normalise_group(
        [{"Titel": "Geheimer Titel", "Unbekannt": "Geheimer Wert"}], TRACKS)
    rationale = G.outcome_for(problems)["rationale"]
    assert "Geheimer" not in rationale
    assert rationale == G.PROBLEM_UNKNOWN_CHILD


def test_child_values_are_coerced_to_text():
    items, _ = G.normalise_group([{"Lfd_Nr": 1, "Titel": None, "Spieldauer": ["x"]}], TRACKS)
    assert items[0] == {"Lfd_Nr": "1", "Titel": "", "Spieldauer": ""}


def test_normalise_accepts_plain_dict_group_definition():
    """Definitions loaded from config.json/run.json are plain dicts, not models."""
    plain = {"max_items": 20, "fields": [{"name": "Titel"}, {"name": "Spieldauer"}]}
    items, _ = G.normalise_group([{"Titel": "A", "Spieldauer": "1'00"}], plain)
    assert items == [{"Titel": "A", "Spieldauer": "1'00"}]
    assert G.max_items(plain) == 20
    assert G.child_names(plain) == ["Titel", "Spieldauer"]


def test_max_items_falls_back_on_nonsense():
    assert G.max_items({"max_items": 0}) == 12
    assert G.max_items({"max_items": "viele"}) == 12
    assert G.max_items({}) == 12


# --------------------------------------------------------------------------- #
# Effective value: edited array wins over raw
# --------------------------------------------------------------------------- #
def test_effective_items_prefers_edited():
    result = {
        "data": {"Titel_Tracks": G.serialise_group([{"Titel": "OCR"}])},
        "edited_data": {"Titel_Tracks": G.serialise_group([{"Titel": "Kurator"}])},
    }
    assert G.effective_items(result, "Titel_Tracks") == [{"Titel": "Kurator"}]


def test_effective_items_falls_back_to_raw():
    result = {"data": {"Titel_Tracks": G.serialise_group([{"Titel": "OCR"}])}}
    assert G.effective_items(result, "Titel_Tracks") == [{"Titel": "OCR"}]


def test_effective_items_honours_an_emptied_group():
    """A curator who removed every entry must not see the raw values return."""
    result = {
        "data": {"Titel_Tracks": G.serialise_group([{"Titel": "OCR"}])},
        "edited_data": {"Titel_Tracks": "[]"},
    }
    assert G.effective_items(result, "Titel_Tracks") == []


def test_effective_items_on_a_card_without_the_group():
    assert G.effective_items({"data": {}}, "Titel_Tracks") == []
    assert G.effective_items({}, "Titel_Tracks") == []


# --------------------------------------------------------------------------- #
# AMIGA Tonband-Karteikarte seed template (case 24/25 at the template level)
# --------------------------------------------------------------------------- #
def test_amiga_template_has_every_required_field():
    from app.services.amiga_template import FIELD_GROUPS, FIELDS

    required = [
        "Bestellnummer", "Tonband_Nr", "Gesamttitel", "Titel_Tracks", "Gesamtspieldauer",
        "Sperrvermerk", "Ort_der_Aufnahme", "Aufnahmedatum", "Aufnahmeleiter", "Tonmeister",
        "Aufnahmetechniker", "Kuenstlerische_Freigabe_Datum", "Kuenstlerische_Freigabe_Gez",
        "Technische_Freigabe_Datum", "Technische_Freigabe_Gez", "Sicherheitsumschnitt_Datum",
        "Sicherheitsumschnitt_Von", "Bemerkungen", "Orchester", "Dirigent_Orchester", "Chor",
        "Dirigent_Chor", "Solisten", "Komponist", "Textdichter", "Bearbeiter", "Verlag",
    ]
    assert FIELDS == required, "field list and order must match the specification"
    assert G.child_names(FIELD_GROUPS["Titel_Tracks"]) == ["Lfd_Nr", "Titel", "Spieldauer"]
    assert G.max_items(FIELD_GROUPS["Titel_Tracks"]) == 20


def test_amiga_group_label_stays_a_normal_field():
    """The group is addressed through `fields`; no parallel field list exists."""
    from app.services.amiga_template import FIELDS
    assert "Titel_Tracks" in FIELDS


def test_amiga_prompt_frames_the_card_type_and_discipline():
    from app.services.amiga_template import PROMPT_TEMPLATE as P
    assert "AMIGA Tonband-Karteikarte" in P
    assert "strukturierte Metadatenerfassung" in P
    for rule in ["Erfinde nichts", "historische Schreibweise", "leeren String",
                 "Formularbezeichnungen sind Struktur", "handschriftliche",
                 "Reihenfolge des Dokuments", "mehrere Namen"]:
        assert rule in P, rule
    assert "{{fields}}" in P, "the field block placeholder must be present"


def test_amiga_prompt_distinguishes_summary_from_item_values():
    """The engine derives this generically; assert it holds for AMIGA."""
    from app.models.schemas import FieldGroup
    from app.services.amiga_template import FIELDS, FIELD_GROUPS, PROMPT_TEMPLATE
    from app.services.ocr_engine import ocr_engine

    groups = {k: FieldGroup(**v) for k, v in FIELD_GROUPS.items()}
    prompt = ocr_engine._generate_prompt(FIELDS, template=PROMPT_TEMPLATE, field_groups=groups)

    assert 'Titel_Tracks[*].Titel' in prompt
    assert 'Titel_Tracks[*].Spieldauer' in prompt
    assert "Gesamttitel" in prompt and "Gesamtspieldauer" in prompt
    # The overall values must never suppress the individual ones.
    assert prompt.count("niemals") >= 3
    assert "Berechne und schätze nichts" in prompt


def test_amiga_seeding_is_idempotent_and_preserves_the_legacy_template():
    from app.models.schemas import TemplateCreate
    from app.services.amiga_template import TEMPLATE_NAME, ensure_seeded
    from app.services.template_service import template_service

    # Start from a known state: another test's context-managed client may already
    # have run the app lifespan, which seeds this template.
    for existing in template_service.list_templates():
        if existing.name in (TEMPLATE_NAME, "AMIGA Tonbandkartei"):
            template_service.delete_template(existing.id)

    legacy = template_service.create_template(
        TemplateCreate(name="AMIGA Tonbandkartei", fields=["Titel", "Spieldauer"])
    )
    try:
        assert ensure_seeded() is True, "first call creates the template"
        assert ensure_seeded() is False, "second call must not duplicate it"

        names = [t.name for t in template_service.list_templates()]
        assert names.count(TEMPLATE_NAME) == 1
        # The flat legacy template is untouched.
        still = template_service.get_template(legacy.id)
        assert still is not None and still.fields == ["Titel", "Spieldauer"]
        assert still.field_groups is None

        seeded = next(t for t in template_service.list_templates() if t.name == TEMPLATE_NAME)
        assert seeded.field_groups["Titel_Tracks"].max_items == 20
    finally:
        for t in template_service.list_templates():
            if t.name in (TEMPLATE_NAME, "AMIGA Tonbandkartei"):
                template_service.delete_template(t.id)


# --------------------------------------------------------------------------- #
# Per-child confidence through _split_extraction (plan case 11)
# --------------------------------------------------------------------------- #
def _split(parsed, field_groups=None):
    from app.services.ocr_engine import ocr_engine

    return ocr_engine._split_extraction(parsed, field_groups)


CONF_RESPONSE = {
    "fields": {
        "Gesamttitel": "Gershwin - Evergreens",
        "Titel_Tracks": [{"Lfd_Nr": "1", "Titel": "The Man I Love", "Spieldauer": "3'21"}],
    },
    "confidence": {
        "Gesamttitel": 0.94,
        "Titel_Tracks": 0.8,                  # group-level badge
        "Titel_Tracks[0].Titel": 0.95,
        "Titel_Tracks[0].Spieldauer": 0.88,
        "Titel_Tracks[19].Lfd_Nr": 0.5,       # last addressable entry
        "Titel_Tracks[0].Erfunden": 0.7,      # child not in the template
        "Erfundene_Gruppe[0].Titel": 0.7,     # group not in the template
        "Titel_Tracks[x].Titel": 0.6,         # not a valid flattened key
        "NichtImTemplate": 0.9,               # scalar not in the template
    },
    "confidence_overall": 0.9,
}


def test_flattened_child_confidence_survives_split():
    """A defined group child keeps its per-child confidence key verbatim."""
    _fields, conf, _overall = _split(CONF_RESPONSE, {"Titel_Tracks": TRACKS})
    assert conf["Titel_Tracks[0].Titel"] == 0.95
    assert conf["Titel_Tracks[0].Spieldauer"] == 0.88
    assert conf["Titel_Tracks[19].Lfd_Nr"] == 0.5
    assert conf["Titel_Tracks"] == 0.8, "a group-level confidence is still allowed"


def test_unknown_group_and_child_confidence_keys_are_dropped():
    """A creative model cannot inject confidence for undefined groups or children."""
    _fields, conf, _overall = _split(CONF_RESPONSE, {"Titel_Tracks": TRACKS})
    assert "Titel_Tracks[0].Erfunden" not in conf
    assert "Erfundene_Gruppe[0].Titel" not in conf
    assert "Titel_Tracks[x].Titel" not in conf
    assert "NichtImTemplate" not in conf


def test_child_confidence_needs_a_group_definition():
    """Without field_groups the flattened keys are dropped, exactly as before the feature."""
    _fields, conf, _overall = _split(CONF_RESPONSE)
    assert sorted(conf) == ["Gesamttitel", "Titel_Tracks"]


def test_child_confidence_is_clamped_like_scalar_confidence():
    """Child keys go through the same coercion, so no second confidence system."""
    parsed = {
        "fields": {"Titel_Tracks": []},
        "confidence": {
            "Titel_Tracks[0].Titel": 1.7,      # above range
            "Titel_Tracks[1].Titel": -0.5,     # below range
            "Titel_Tracks[2].Titel": "keine",  # unusable
        },
    }
    _fields, conf, _overall = _split(parsed, {"Titel_Tracks": TRACKS})
    assert conf["Titel_Tracks[0].Titel"] == 1.0
    assert conf["Titel_Tracks[1].Titel"] == 0.0
    assert "Titel_Tracks[2].Titel" not in conf


# --------------------------------------------------------------------------- #
# Scalar field rules must not be applied to a group's serialised array (§2.4)
# --------------------------------------------------------------------------- #
def _run_rules(data, field_rules, skip_fields=None, corrector=None):
    """run_validation with the LLM corrector stubbed out — never a real call."""
    import threading

    from app.services.validation import runner

    calls: list = []
    original = runner.invoke_corrector

    def _stub(field, value, rule, cap, key):
        calls.append((field, value))
        return {"status": "corrected", "rationale": "stub", "proposal": "stub"}

    runner.invoke_corrector = _stub
    try:
        outcomes = runner.run_validation(
            data=data,
            field_rules=field_rules,
            corrector_enabled=True,
            cap_state={"used": 0, "cap": 100, "lock": threading.Lock()},
            api_key="test-key-not-used",
            skip_fields=skip_fields,
        )
    finally:
        runner.invoke_corrector = original
    return outcomes, calls


GROUP_JSON = '[{"Lfd_Nr":"1","Titel":"The Man I Love","Spieldauer":"3\'21"}]'
DIGITS_ONLY = {"pattern": r"^\d{4}$", "corrector_enabled": True}


def test_scalar_rules_skip_group_labels():
    """A regex over a serialised array is meaningless, so the group is skipped."""
    outcomes, _calls = _run_rules(
        {"Titel_Tracks": GROUP_JSON}, {"Titel_Tracks": DIGITS_ONLY},
        skip_fields=["Titel_Tracks"],
    )
    assert outcomes == {}, "no scalar outcome may be produced for a group label"


def test_group_json_is_never_handed_to_the_corrector():
    """Without the skip the corrector would receive card content as a field value."""
    _outcomes, calls = _run_rules(
        {"Titel_Tracks": GROUP_JSON}, {"Titel_Tracks": DIGITS_ONLY},
        skip_fields=["Titel_Tracks"],
    )
    assert calls == [], "the LLM corrector must never be invoked for a group label"


def test_scalar_rules_still_apply_to_ordinary_fields():
    """The skip is surgical: neighbouring scalar fields keep their rules."""
    outcomes, calls = _run_rules(
        {"Titel_Tracks": GROUP_JSON, "Bestellnummer": "abc"},
        {"Titel_Tracks": DIGITS_ONLY, "Bestellnummer": DIGITS_ONLY},
        skip_fields=["Titel_Tracks"],
    )
    assert "Titel_Tracks" not in outcomes
    assert outcomes["Bestellnummer"]["rule_failed"] == "regex"
    assert [f for f, _v in calls] == ["Bestellnummer"]


def test_run_validation_without_skip_is_unchanged():
    """Default argument keeps every existing call site behaving exactly as before."""
    outcomes, _calls = _run_rules({"Bestellnummer": "abc"}, {"Bestellnummer": {"pattern": r"^\d+$"}})
    assert outcomes["Bestellnummer"]["status"] == "invalid"
    assert outcomes["Bestellnummer"]["original_value"] == "abc"
