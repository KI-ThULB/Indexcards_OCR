"""The shared JSON Schema contract must stay in sync with the backend models.

`packages/shared-types/schemas/*.schema.json` is the cross-language contract from
which the TypeScript interfaces and Pydantic models in
`packages/shared-types/generated/` are produced. Nothing imports the generated
types at runtime today, which is exactly why drift goes unnoticed: `field_groups`
was added to the backend models without reaching either shared schema, while the
comparable side-maps `field_rules` and `authority_bindings` were modelled in both.

Repeatable groups touch two schema files, because the group definitions travel
with the template *and* with the batch config frozen from it. Following the
convention already used for `FieldRule` and `AuthorityBinding`, the definitions
are duplicated verbatim per file rather than cross-referenced (no schema here
uses an external `$ref`); the generator de-duplicates them, and
:func:`test_duplicated_group_definitions_do_not_drift` keeps the copies honest.

These tests derive the expectation from `app.models.schemas` rather than
restating it, so they fail whichever side moves.
"""
import json
from pathlib import Path
from typing import Any, Dict, Tuple, Type

import pytest
from pydantic import BaseModel

from app.models.schemas import (
    BatchConfig,
    BatchCreate,
    FieldGroup,
    GroupChild,
    Template,
    TemplateCreate,
    TemplateUpdate,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SHARED = REPO_ROOT / "packages" / "shared-types"
SCHEMAS = SHARED / "schemas"

TEMPLATE_SCHEMA = "template.schema.json"
BATCH_SCHEMA = "batch.schema.json"

# The backend is deployable on its own (see Dockerfile), so the monorepo package
# need not be present. Skip rather than fail in that case.
pytestmark = pytest.mark.skipif(
    not SHARED.is_dir(), reason="shared-types package not present (standalone backend checkout)"
)

# Every backend shape that carries `field_groups`, and the schema file that models it.
GROUP_BEARING_SHAPES: Dict[str, Tuple[str, Type[BaseModel]]] = {
    "Template": (TEMPLATE_SCHEMA, Template),
    "TemplateCreate": (TEMPLATE_SCHEMA, TemplateCreate),
    "TemplateUpdate": (TEMPLATE_SCHEMA, TemplateUpdate),
    "BatchConfig": (BATCH_SCHEMA, BatchConfig),
    "BatchCreate": (BATCH_SCHEMA, BatchCreate),
}

# Both schema files must define the group shapes they reference.
GROUP_DEFINITION_FILES = [TEMPLATE_SCHEMA, BATCH_SCHEMA]

SHAPE_IDS = sorted(GROUP_BEARING_SHAPES)


def _definitions(schema_file: str) -> Dict[str, Any]:
    return json.loads((SCHEMAS / schema_file).read_text(encoding="utf-8"))["definitions"]


def _shape(name: str) -> Dict[str, Any]:
    schema_file, _model = GROUP_BEARING_SHAPES[name]
    return _definitions(schema_file)[name]


def test_every_backend_shape_carrying_field_groups_is_covered() -> None:
    """Guards the guard: a new group-bearing model must be added to this matrix."""
    from app.models import schemas as backend_schemas

    declared = {
        name
        for name in dir(backend_schemas)
        if isinstance(getattr(backend_schemas, name, None), type)
        and issubclass(getattr(backend_schemas, name), BaseModel)
        and "field_groups" in getattr(backend_schemas, name).model_fields
    }
    assert declared == set(GROUP_BEARING_SHAPES), (
        "app/models/schemas.py declares field_groups on "
        f"{sorted(declared)} but this test covers {SHAPE_IDS}"
    )


@pytest.mark.parametrize("name", SHAPE_IDS)
def test_schema_models_field_groups(name: str) -> None:
    """Whatever carries field_groups in the backend must carry it in the contract."""
    schema_file, _model = GROUP_BEARING_SHAPES[name]
    assert "field_groups" in _shape(name)["properties"], (
        f"{name} declares field_groups in app/models/schemas.py but not in "
        f"{schema_file} — regenerate the shared types after adding it"
    )


@pytest.mark.parametrize("name", SHAPE_IDS)
def test_field_groups_is_optional_and_nullable(name: str) -> None:
    """A scalar-only template or batch must stay valid, as before the side-map existed."""
    definition = _shape(name)
    _schema_file, model = GROUP_BEARING_SHAPES[name]
    assert "field_groups" not in (definition.get("required") or []), (
        f"{name}.field_groups must not be required — scalar-only configs carry none"
    )
    prop = definition["properties"]["field_groups"]
    assert prop.get("default", "missing") is None, "the absent case must default to null"
    assert {"type": "null"} in prop["anyOf"], "field_groups must accept null"
    # Matches the backend: Optional[...] with a None default.
    assert model.model_fields["field_groups"].is_required() is False


@pytest.mark.parametrize("name", SHAPE_IDS)
def test_group_label_is_the_map_key(name: str) -> None:
    """field_groups is keyed by the group label, like field_rules and authority_bindings."""
    prop = _shape(name)["properties"]["field_groups"]
    mapping = next(o for o in prop["anyOf"] if o.get("type") == "object")
    assert mapping["additionalProperties"] == {"$ref": "#/definitions/FieldGroup"}


@pytest.mark.parametrize("name", SHAPE_IDS)
def test_field_groups_mirrors_the_sibling_side_maps(name: str) -> None:
    """Same construction as field_rules — one mechanism, not a second model."""
    props = _shape(name)["properties"]

    def shape(prop: Dict[str, Any]) -> Tuple[Any, Any]:
        return sorted(prop.keys() - {"description", "title"}), prop.get("default")

    assert shape(props["field_groups"]) == shape(props["field_rules"])
    assert shape(props["field_groups"]) == shape(props["authority_bindings"])


@pytest.mark.parametrize("schema_file", GROUP_DEFINITION_FILES)
def test_field_group_definition_matches_the_backend_model(schema_file: str) -> None:
    """Children, required-ness and the max_items default all come from the backend."""
    definition = _definitions(schema_file)["FieldGroup"]
    assert sorted(definition["properties"]) == sorted(FieldGroup.model_fields)

    required = {n for n, f in FieldGroup.model_fields.items() if f.is_required()}
    assert set(definition.get("required") or []) == required == {"fields"}

    # The generic default must not drift from the backend's.
    assert (
        definition["properties"]["max_items"]["default"]
        == FieldGroup.model_fields["max_items"].default
        == 12
    )
    assert definition["properties"]["fields"]["items"] == {"$ref": "#/definitions/GroupChild"}


@pytest.mark.parametrize("schema_file", GROUP_DEFINITION_FILES)
def test_group_child_definition_matches_the_backend_model(schema_file: str) -> None:
    """`name` is identifier and label both — no display-label abstraction is introduced."""
    definition = _definitions(schema_file)["GroupChild"]
    assert sorted(definition["properties"]) == sorted(GroupChild.model_fields) == ["description", "name"]

    required = {n for n, f in GroupChild.model_fields.items() if f.is_required()}
    assert set(definition.get("required") or []) == required == {"name"}


@pytest.mark.parametrize("name", ["GroupChild", "FieldGroup"])
def test_duplicated_group_definitions_do_not_drift(name: str) -> None:
    """The per-file copies must stay byte-identical.

    The generator merges definitions across schema files and keeps the first it
    sees (files are read in sorted order, so batch wins over template). Identical
    copies make that resolution irrelevant; divergent ones would silently pick a
    winner, which is how AuthorityBinding's two copies already differ.
    """
    rendered = {
        json.dumps(_definitions(f)[name], sort_keys=True) for f in GROUP_DEFINITION_FILES
    }
    assert len(rendered) == 1, f"{name} differs between {GROUP_DEFINITION_FILES}"


def test_a_scalar_only_template_still_validates_against_the_contract() -> None:
    """The regression the additive side-map exists to avoid."""
    definition = _definitions(TEMPLATE_SCHEMA)["TemplateCreate"]
    scalar_only = TemplateCreate(name="Museumskartei", fields=["Titel", "Komponist"])
    # Everything the contract demands is satisfiable without mentioning groups.
    assert set(definition["required"]) <= set(scalar_only.model_dump(exclude_none=True))
    assert scalar_only.field_groups is None


def test_a_scalar_only_batch_still_validates_against_the_contract() -> None:
    """A batch created from a group-free template carries no field_groups."""
    definition = _definitions(BATCH_SCHEMA)["BatchCreate"]
    scalar_only = BatchCreate(custom_name="Museumskartei-01", session_id="s-1")
    assert set(definition["required"]) <= set(scalar_only.model_dump(exclude_none=True))
    assert scalar_only.field_groups is None
    assert BatchConfig(fields=["Titel"]).field_groups is None


@pytest.mark.parametrize("artefact", ["generated/ts/index.ts", "generated/py/template.py", "generated/py/batch.py"])
def test_generated_artefacts_are_not_stale(artefact: str) -> None:
    """Guards the easy mistake: schema edited, generator never run."""
    path = SHARED / artefact
    if not path.is_file():
        pytest.skip(f"{artefact} not generated in this checkout")
    text = path.read_text(encoding="utf-8")
    for symbol in ("field_groups", "FieldGroup", "GroupChild"):
        assert symbol in text, (
            f"{artefact} does not mention {symbol} — run `npm run generate` in "
            f"packages/shared-types after changing a schema"
        )


def test_generated_typescript_has_no_duplicate_group_interfaces() -> None:
    """Duplicating the definitions per schema file must not duplicate the output."""
    path = SHARED / "generated" / "ts" / "index.ts"
    if not path.is_file():
        pytest.skip("generated/ts/index.ts not present")
    text = path.read_text(encoding="utf-8")
    for name in ("GroupChild", "FieldGroup"):
        assert text.count(f"export interface {name} {{") == 1, f"{name} emitted more than once"
