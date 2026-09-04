"""Curator editing of repeatable-group entries via PATCH.

The API is granular (group + index + child + value) while storage is the whole
edited array, so edits stay independent and add/remove/reorder cannot orphan
per-child keys.
"""
import json

import pytest

from app.core.checkpoint import read_checkpoint, write_checkpoint
from app.models.schemas import FieldGroup, GroupChild, TemplateCreate
from app.services.batch_manager import batch_manager
from app.services.validation import groups as G

TRACKS = FieldGroup(
    max_items=3,   # deliberately small so the cap is testable
    fields=[GroupChild(name="Lfd_Nr"), GroupChild(name="Titel"), GroupChild(name="Spieldauer")],
)
FIELDS = ["Gesamttitel", "Titel_Tracks", "Gesamtspieldauer"]


@pytest.fixture(autouse=True)
def _clean_batches():
    before = set(batch_manager.list_batches())
    yield
    for name in set(batch_manager.list_batches()) - before:
        try:
            batch_manager.delete_batch(name)
        except Exception:
            pass


@pytest.fixture
def batch():
    """A batch whose config declares the group, holding one card with 2 tracks."""
    sid = batch_manager.generate_session_id()
    session = batch_manager.get_temp_session_path(sid)
    (session / "card.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 16 + b"\xff\xd9")
    name = batch_manager.create_batch(
        custom_name="groups", session_id=sid, fields=FIELDS,
        field_groups={"Titel_Tracks": TRACKS.dict()},
    )
    items = [
        {"Lfd_Nr": "1", "Titel": "The Man I Love", "Spieldauer": "3'21"},
        {"Lfd_Nr": "2", "Titel": "I Got Rhythm", "Spieldauer": "2'48"},
    ]
    write_checkpoint(
        batch_manager.get_batch_path(name) / "checkpoint.json",
        [{"filename": "card.jpg", "batch": name, "success": True, "duration": 1.0,
          "data": {"Gesamttitel": "Gershwin - Evergreens",
                   "Titel_Tracks": G.serialise_group(items),
                   "Gesamtspieldauer": "10'15"}}],
        [],
    )
    return name


def _items(name):
    results, _ = read_checkpoint(batch_manager.get_batch_path(name) / "checkpoint.json")
    return G.effective_items(results[0], "Titel_Tracks")


def _patch(client, name, body):
    return client.patch(f"/api/v1/batches/{name}/results/card.jpg", json=body)


# --------------------------------------------------------------------------- #
# Value edits (case 11: independent per-child edits)
# --------------------------------------------------------------------------- #
def test_edit_one_child_value(client, batch):
    r = _patch(client, batch, {"group": "Titel_Tracks", "index": 0,
                               "field": "Titel", "value": "The Man I Love (korrigiert)"})
    assert r.status_code == 200, r.text
    items = _items(batch)
    assert items[0]["Titel"] == "The Man I Love (korrigiert)"
    assert items[0]["Spieldauer"] == "3'21"      # untouched
    assert items[1]["Titel"] == "I Got Rhythm"   # other entry untouched


def test_edits_to_different_entries_are_independent(client, batch):
    """Titel_Tracks[0].Titel and Titel_Tracks[1].Titel must not overwrite each other."""
    _patch(client, batch, {"group": "Titel_Tracks", "index": 0, "field": "Titel", "value": "AAA"})
    _patch(client, batch, {"group": "Titel_Tracks", "index": 1, "field": "Titel", "value": "BBB"})
    items = _items(batch)
    assert [i["Titel"] for i in items] == ["AAA", "BBB"]


def test_edit_preserves_raw_ocr_value(client, batch):
    """The edit lands in edited_data; data keeps the original extraction."""
    _patch(client, batch, {"group": "Titel_Tracks", "index": 0, "field": "Titel", "value": "Neu"})
    results, _ = read_checkpoint(batch_manager.get_batch_path(batch) / "checkpoint.json")
    raw = G.parse_group(results[0]["data"]["Titel_Tracks"])
    edited = G.parse_group(results[0]["edited_data"]["Titel_Tracks"])
    assert raw[0]["Titel"] == "The Man I Love"
    assert edited[0]["Titel"] == "Neu"


def test_edit_can_clear_a_child(client, batch):
    r = _patch(client, batch, {"group": "Titel_Tracks", "index": 0,
                               "field": "Spieldauer", "value": ""})
    assert r.status_code == 200
    assert _items(batch)[0]["Spieldauer"] == ""


# --------------------------------------------------------------------------- #
# Structural operations (cases 12–14)
# --------------------------------------------------------------------------- #
def test_add_entry_appends_by_default(client, batch):
    r = _patch(client, batch, {"group": "Titel_Tracks", "group_op": "add"})
    assert r.status_code == 200, r.text
    items = _items(batch)
    assert len(items) == 3
    assert items[2] == {"Lfd_Nr": "", "Titel": "", "Spieldauer": ""}


def test_add_entry_at_position(client, batch):
    _patch(client, batch, {"group": "Titel_Tracks", "group_op": "add", "index": 0})
    items = _items(batch)
    assert len(items) == 3
    assert items[0]["Titel"] == ""
    assert items[1]["Titel"] == "The Man I Love"


def test_add_beyond_max_items_is_refused(client, batch):
    _patch(client, batch, {"group": "Titel_Tracks", "group_op": "add"})   # now 3 == max
    r = _patch(client, batch, {"group": "Titel_Tracks", "group_op": "add"})
    assert r.status_code == 400
    assert "maximum of 3" in r.text
    assert len(_items(batch)) == 3, "the refused add must not have been applied"


def test_remove_entry(client, batch):
    r = _patch(client, batch, {"group": "Titel_Tracks", "group_op": "remove", "index": 0})
    assert r.status_code == 200
    items = _items(batch)
    assert len(items) == 1
    assert items[0]["Titel"] == "I Got Rhythm"


def test_remove_leaves_no_orphaned_child_data(client, batch):
    """Storing the whole array means a removal cannot leave stale per-child keys."""
    _patch(client, batch, {"group": "Titel_Tracks", "index": 1, "field": "Titel", "value": "XYZ"})
    _patch(client, batch, {"group": "Titel_Tracks", "group_op": "remove", "index": 1})
    results, _ = read_checkpoint(batch_manager.get_batch_path(batch) / "checkpoint.json")
    raw_edited = results[0]["edited_data"]["Titel_Tracks"]
    assert "XYZ" not in raw_edited
    assert len(G.parse_group(raw_edited)) == 1


def test_reorder_entries(client, batch):
    r = _patch(client, batch, {"group": "Titel_Tracks", "group_op": "move",
                               "index": 0, "to_index": 1})
    assert r.status_code == 200
    assert [i["Titel"] for i in _items(batch)] == ["I Got Rhythm", "The Man I Love"]


def test_reorder_keeps_values_with_their_entry(client, batch):
    _patch(client, batch, {"group": "Titel_Tracks", "group_op": "move", "index": 1, "to_index": 0})
    items = _items(batch)
    assert items[0] == {"Lfd_Nr": "2", "Titel": "I Got Rhythm", "Spieldauer": "2'48"}


def test_emptying_the_group_persists(client, batch):
    _patch(client, batch, {"group": "Titel_Tracks", "group_op": "remove", "index": 1})
    _patch(client, batch, {"group": "Titel_Tracks", "group_op": "remove", "index": 0})
    assert _items(batch) == []


# --------------------------------------------------------------------------- #
# Guards
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("body,expected", [
    ({"group": "Unbekannt", "index": 0, "field": "Titel", "value": "x"}, "Unknown group"),
    ({"group": "Titel_Tracks", "index": 9, "field": "Titel", "value": "x"}, "out of range"),
    ({"group": "Titel_Tracks", "index": -1, "field": "Titel", "value": "x"}, "out of range"),
    ({"group": "Titel_Tracks", "field": "Titel", "value": "x"}, "out of range"),
    ({"group": "Titel_Tracks", "index": 0, "field": "Erfunden", "value": "x"}, "Unknown child"),
    ({"group": "Titel_Tracks", "index": 0, "value": "x"}, "requires 'field'"),
    ({"group": "Titel_Tracks", "group_op": "remove"}, "out of range"),
    ({"group": "Titel_Tracks", "group_op": "move", "index": 0}, "Target index"),
    ({"group": "Titel_Tracks", "group_op": "explodieren"}, "Unknown group operation"),
])
def test_bad_group_patches_are_refused(client, batch, body, expected):
    r = _patch(client, batch, body)
    assert r.status_code == 400, r.text
    assert expected in r.text


def test_scalar_patch_still_requires_a_field(client, batch):
    """`field` only became optional on the model for structural group ops."""
    r = _patch(client, batch, {"value": "x"})
    assert r.status_code == 400
    assert "'field' is required" in r.text


def test_group_patch_on_unknown_card_is_404(client, batch):
    r = client.patch(f"/api/v1/batches/{batch}/results/nope.jpg",
                     json={"group": "Titel_Tracks", "group_op": "add"})
    assert r.status_code == 404


def test_scalar_editing_is_unchanged(client, batch):
    """Case 1/2: the pre-existing scalar path must behave exactly as before."""
    r = _patch(client, batch, {"field": "Gesamttitel", "value": "Korrigiert",
                               "validation_status": "verified"})
    assert r.status_code == 200
    results, _ = read_checkpoint(batch_manager.get_batch_path(batch) / "checkpoint.json")
    assert results[0]["edited_data"]["Gesamttitel"] == "Korrigiert"
    assert results[0]["validation"]["Gesamttitel"]["status"] == "verified"


# --------------------------------------------------------------------------- #
# Audit + persistence
# --------------------------------------------------------------------------- #
def test_group_operations_are_auditable(client, batch):
    r = _patch(client, batch, {
        "group": "Titel_Tracks", "group_op": "add",
        "audit_entry": {"id": "g1", "op": "group-add", "column": "Titel_Tracks",
                        "label": "Eintrag #3 hinzugefügt", "affected": 1,
                        "scope": "all", "source": "group-edit"},
    })
    assert r.status_code == 200
    _, audit = read_checkpoint(batch_manager.get_batch_path(batch) / "checkpoint.json")
    assert [a["id"] for a in audit] == ["g1"]
    assert audit[0]["op"] == "group-add"


def test_edits_survive_a_reload(client, batch):
    """Case 15: persistence, read back through the results endpoint."""
    _patch(client, batch, {"group": "Titel_Tracks", "index": 0, "field": "Titel", "value": "Bleibt"})
    body = client.get(f"/api/v1/batches/{batch}/results").json()
    edited = G.parse_group(body["results"][0]["edited_data"]["Titel_Tracks"])
    assert edited[0]["Titel"] == "Bleibt"


def test_stored_array_stays_canonical(client, batch):
    """Every entry carries exactly the defined children, in template order."""
    _patch(client, batch, {"group": "Titel_Tracks", "group_op": "add", "index": 0})
    results, _ = read_checkpoint(batch_manager.get_batch_path(batch) / "checkpoint.json")
    stored = json.loads(results[0]["edited_data"]["Titel_Tracks"])
    for item in stored:
        assert list(item.keys()) == ["Lfd_Nr", "Titel", "Spieldauer"]


def test_config_endpoint_exposes_field_groups(client, batch):
    body = client.get(f"/api/v1/batches/{batch}/config").json()
    assert "Titel_Tracks" in body["field_groups"]
    assert body["field_groups"]["Titel_Tracks"]["max_items"] == 3


def test_template_roundtrip_persists_groups(client):
    from app.services.template_service import template_service
    tpl = template_service.create_template(
        TemplateCreate(name="Gruppen-Test", fields=FIELDS,
                       field_groups={"Titel_Tracks": TRACKS})
    )
    try:
        fetched = template_service.get_template(tpl.id)
        assert fetched.field_groups["Titel_Tracks"].max_items == 3
        listed = client.get("/api/v1/templates/").json()
        mine = [t for t in listed if t["id"] == tpl.id][0]
        assert mine["field_groups"]["Titel_Tracks"]["fields"][1]["name"] == "Titel"
    finally:
        template_service.delete_template(tpl.id)


# --------------------------------------------------------------------------- #
# Revalidation must not drop a group's shape outcome
# --------------------------------------------------------------------------- #
def _config(name):
    return batch_manager.get_batch_path(name) / "config.json"


def _set_field_rules(name, rules):
    path = _config(name)
    cfg = json.loads(path.read_text())
    cfg["field_rules"] = rules
    path.write_text(json.dumps(cfg))


def _validation(name):
    results, _ = read_checkpoint(batch_manager.get_batch_path(name) / "checkpoint.json")
    return results[0].get("validation") or {}


def _record_group_outcome(name, problems):
    """Store what extraction records for a group whose shape was wrong."""
    ckpt = batch_manager.get_batch_path(name) / "checkpoint.json"
    results, audit = read_checkpoint(ckpt)
    results[0]["validation"] = {"Titel_Tracks": G.outcome_for(problems)}
    write_checkpoint(ckpt, results, audit)


def test_revalidate_keeps_the_group_shape_outcome(client, batch):
    """A malformed-group indicator is the curator's only signal; revalidation must keep it.

    Only extraction can observe the shape the model returned — data[group] already
    holds the normalised array — so a dropped outcome could never be recovered.
    """
    _set_field_rules(batch, {"Gesamttitel": {"pattern": ".+"}})
    _record_group_outcome(batch, ["group_malformed"])

    r = client.post(f"/api/v1/batches/{batch}/revalidate")
    assert r.status_code == 200

    after = _validation(batch)
    assert after["Titel_Tracks"]["status"] == "invalid"
    assert after["Titel_Tracks"]["rule_failed"] == "group_shape"
    assert after["Titel_Tracks"]["rationale"] == "group_malformed"
    # the scalar rule still ran
    assert after["Gesamttitel"]["status"] == "valid"


def test_revalidate_does_not_apply_scalar_rules_to_a_group(client, batch):
    """A rule mistakenly configured on a group label must not produce an outcome."""
    _set_field_rules(batch, {"Titel_Tracks": {"pattern": r"^\d{4}$"}})

    r = client.post(f"/api/v1/batches/{batch}/revalidate")
    assert r.status_code == 200
    assert "Titel_Tracks" not in _validation(batch)


def test_revalidate_never_writes_card_content_for_a_group(client, batch):
    """original_value would otherwise carry the serialised card content (§7)."""
    _set_field_rules(batch, {"Titel_Tracks": {"pattern": r"^\d{4}$"}})
    client.post(f"/api/v1/batches/{batch}/revalidate")

    blob = json.dumps(_validation(batch), ensure_ascii=False)
    assert "The Man I Love" not in blob
    assert "Gershwin" not in blob


def test_revalidate_leaves_group_data_untouched(client, batch):
    """Revalidation re-runs rules only; the entries themselves must not move."""
    before = _items(batch)
    _set_field_rules(batch, {"Gesamttitel": {"pattern": ".+"}})
    client.post(f"/api/v1/batches/{batch}/revalidate")
    assert _items(batch) == before
