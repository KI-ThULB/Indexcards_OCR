"""The shared template contract must stay in sync with the backend Template models.

`packages/shared-types/schemas/template.schema.json` is the cross-language
contract from which the TypeScript interfaces and Pydantic models in
`packages/shared-types/generated/` are produced. Nothing imports the generated
types at runtime today, which is exactly why drift goes unnoticed: `field_groups`
was added to the backend models without reaching the shared schema, while the
comparable side-maps `field_rules` and `authority_bindings` were modelled there.

These tests derive the expectation from `app.models.schemas` rather than
restating it, so they fail whichever side moves.
"""
import json
from pathlib import Path
from typing import Any, Dict, Type

import pytest
from pydantic import BaseModel

from app.models.schemas import FieldGroup, GroupChild, Template, TemplateCreate, TemplateUpdate

REPO_ROOT = Path(__file__).resolve().parents[3]
SHARED = REPO_ROOT / "packages" / "shared-types"
SCHEMA_PATH = SHARED / "schemas" / "template.schema.json"

# The backend is deployable on its own (see Dockerfile), so the monorepo package
# need not be present. Skip rather than fail in that case.
pytestmark = pytest.mark.skipif(
    not SHARED.is_dir(), reason="shared-types package not present (standalone backend checkout)"
)

TEMPLATE_MODELS: Dict[str, Type[BaseModel]] = {
    "Template": Template,
    "TemplateCreate": TemplateCreate,
    "TemplateUpdate": TemplateUpdate,
}


def _definitions() -> Dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))["definitions"]


@pytest.mark.parametrize("name", sorted(TEMPLATE_MODELS))
def test_schema_models_field_groups_for_every_template_shape(name: str) -> None:
    """Whatever carries field_groups in the backend must carry it in the contract."""
    definition = _definitions()[name]
    assert "field_groups" in definition["properties"], (
        f"{name} declares field_groups in app/models/schemas.py but not in "
        f"template.schema.json — regenerate the shared types after adding it"
    )


@pytest.mark.parametrize("name", sorted(TEMPLATE_MODELS))
def test_field_groups_is_optional_and_nullable(name: str) -> None:
    """A scalar-only template must stay valid, exactly as before the side-map existed."""
    definition = _definitions()[name]
    assert "field_groups" not in (definition.get("required") or []), (
        f"{name}.field_groups must not be required — scalar-only templates carry none"
    )
    prop = definition["properties"]["field_groups"]
    assert prop.get("default", "missing") is None, "the absent case must default to null"
    assert {"type": "null"} in prop["anyOf"], "field_groups must accept null"
    # Matches the backend: Optional[...] with a None default.
    assert TEMPLATE_MODELS[name].model_fields["field_groups"].is_required() is False


@pytest.mark.parametrize("name", sorted(TEMPLATE_MODELS))
def test_group_label_is_the_map_key(name: str) -> None:
    """field_groups is keyed by the group label, like field_rules and authority_bindings."""
    prop = _definitions()[name]["properties"]["field_groups"]
    mapping = next(o for o in prop["anyOf"] if o.get("type") == "object")
    assert mapping["additionalProperties"] == {"$ref": "#/definitions/FieldGroup"}


def test_field_groups_mirrors_the_sibling_side_maps() -> None:
    """Same construction as field_rules — one mechanism, not a second template model."""
    props = _definitions()["Template"]["properties"]
    shape = lambda p: (sorted(p.keys() - {"description", "title"}), p.get("default"))  # noqa: E731
    assert shape(props["field_groups"]) == shape(props["field_rules"])
    assert shape(props["field_groups"]) == shape(props["authority_bindings"])


def test_field_group_definition_matches_the_backend_model() -> None:
    """Children, required-ness and the max_items default all come from the backend."""
    definition = _definitions()["FieldGroup"]
    assert sorted(definition["properties"]) == sorted(FieldGroup.model_fields)

    required = {n for n, f in FieldGroup.model_fields.items() if f.is_required()}
    assert set(definition.get("required") or []) == required == {"fields"}

    # The generic default must not drift from the backend's.
    assert definition["properties"]["max_items"]["default"] == FieldGroup.model_fields["max_items"].default == 12
    assert definition["properties"]["fields"]["items"] == {"$ref": "#/definitions/GroupChild"}


def test_group_child_definition_matches_the_backend_model() -> None:
    """`name` is identifier and label both — no display-label abstraction is introduced."""
    definition = _definitions()["GroupChild"]
    assert sorted(definition["properties"]) == sorted(GroupChild.model_fields) == ["description", "name"]

    required = {n for n, f in GroupChild.model_fields.items() if f.is_required()}
    assert set(definition.get("required") or []) == required == {"name"}


def test_a_scalar_only_template_still_validates_against_the_contract() -> None:
    """The regression the additive side-map exists to avoid."""
    definition = _definitions()["TemplateCreate"]
    scalar_only = TemplateCreate(name="Museumskartei", fields=["Titel", "Komponist"])
    # Everything the contract demands is satisfiable without mentioning groups.
    assert set(definition["required"]) <= set(scalar_only.model_dump(exclude_none=True))
    assert scalar_only.field_groups is None


@pytest.mark.parametrize("artefact", ["generated/ts/index.ts", "generated/py/template.py"])
def test_generated_artefacts_are_not_stale(artefact: str) -> None:
    """Guards the easy mistake: schema edited, generator never run."""
    path = SHARED / artefact
    if not path.is_file():
        pytest.skip(f"{artefact} not generated in this checkout")
    text = path.read_text(encoding="utf-8")
    for symbol in ("field_groups", "FieldGroup", "GroupChild"):
        assert symbol in text, (
            f"{artefact} does not mention {symbol} — run `npm run generate` in "
            f"packages/shared-types after changing template.schema.json"
        )
