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
