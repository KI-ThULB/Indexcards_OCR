# Repeatable Field Groups — Implementation Plan

> **Status: APPROVED, IN IMPLEMENTATION.**
> Follow-up feature to the Bulk / Multi-Batch Processing workflow, which was
> merged into `main` as PR #5 (merge commit `673afe4`). Implementation proceeds
> on `feat/repeatable-groups`, branched from that merge.
> This document is self-contained: a fresh session can execute it without prior
> conversation context.
>
> Verified against the merged `main` before implementation: every referenced
> existing file is present, and all ten load-bearing code assumptions still hold
> (`data`/`edited_data` are `Dict[str, str]`, `confidence` is `Dict[str, float]`,
> `Template.fields` is `List[str]`, no `field_groups` or `ResultPatch.group`
> exists yet, `_split_extraction` still filters on `k in fields`, and
> `create_run` still freezes `schema_fields`).

---

## 1. Purpose and architectural decisions

### The problem

A template currently holds a flat list of scalar field labels. For AMIGA tape index
cards this loses information. One card carries:

- one overall title (*Gesamttitel*),
- several individual track titles,
- one duration per track,
- one overall duration (*Gesamtspieldauer*).

```
Gesamttitel:   Gershwin - Evergreens

1 | The Man I Love | 3'21
2 | I Got Rhythm   | 2'48
3 | Summertime     | 4'06

Gesamtspieldauer: 10'15
```

Flattening this to `Titel = "Gershwin - Evergreens"` and `Spieldauer = "10'15"`
discards every track. The repeating title↔duration relationship must survive
extraction, curation and export.

### Approved decisions

These were agreed during architectural analysis and are **not** open for
re-litigation during implementation.

| # | Decision | Rationale |
|---|---|---|
| R1 | Keep the flat `Template.fields` list. Add an **additive optional `field_groups` side-map** keyed by label. The group label itself stays in `fields`. | Mirrors the two mechanisms the codebase already uses (`field_rules`, `authority_bindings`). Preserves field order and every existing iteration site. No second template system. |
| R2 | **Do NOT widen `ExtractionResult.data` to `Dict[str, Any]`.** Store a group's value as a canonical **JSON string** in `data[groupLabel]`. | `data: Dict[str, str]` is load-bearing: `process_batch` builds `ExtractionResult(**res)` on every progress tick, and a real array raises `ValidationError`, which `run_ocr_task` turns into a **failed batch** (verified empirically). JSON-in-a-string is the codebase's own existing convention (`data["_entries"]`) and confines the regression surface. |
| R3 | Confidence uses **flattened keys** in the existing `Dict[str, float]`: `Titel_Tracks[0].Titel`. | No second confidence system. Requires one targeted change to `_split_extraction`'s key filter. |
| R4 | Curator edits for a group are stored as a **canonical JSON string of the whole edited array** under `edited_data[groupLabel]`; the **PATCH API addresses a single child** via `group` + `index` + `field`. | Keeps `edited_data: Dict[str, str]`. Per-child edits stay independent (separate array elements), and structural operations (add/remove/reorder) have a natural home. See §4.3 for why per-child *keys* were rejected. |
| R5 | CSV: **one row per source card**, with numbered group columns frozen at `max_items`, a `_count` column and a lossless `_overflow_json` column. | Preserves the established `_ocr`/`_edited`/`_confidence` triplet convention, so curator edits and per-child confidence are exported. Deterministic width without a pre-pass. Nothing silently flattened or dropped. |
| R6 | `max_items = 20` for the AMIGA `Titel_Tracks` group. | Operator decision. |
| R7 | Malformed group output **never** fails a batch. It normalises to a safe empty group plus a validation indication. | Bulk runs are unattended; one bad card must not stop 14,000. |
| R8 | The existing `_entries` (Findmittel) workflow is **not refactored**. Its known curator-edit defect is out of scope (§15). | Scope control. The new feature may use the same *conceptual* mechanism without touching that code path. |
| R9 | Bulk Processing freezes `field_groups` alongside the existing frozen schema. No Bulk-specific extraction semantics. | The orchestrator stays pure orchestration. |

---

## 2. Exact backend changes

### 2.1 `app/models/schemas.py`

New models:

```python
class GroupChild(BaseModel):
    """One child field inside a repeatable group.

    `name` is both the identifier and the display label, exactly as scalar field
    labels work today (the existing AMIGA template already uses strings like
    "Tonband-Nr." directly). No separate label abstraction is introduced.
    """
    name: str
    description: Optional[str] = None        # instruction passed to the VLM

class FieldGroup(BaseModel):
    """A repeatable group of child fields.

    Zero, one or many entries may occur on a card. `max_items` freezes the CSV
    width; entries beyond it are preserved in an overflow column, never dropped.
    """
    description: Optional[str] = None
    fields: List[GroupChild]
    max_items: int = 12
```

Extended models — each gains the same optional field, defaulting to `None`:

| Model | Added |
|---|---|
| `Template` | `field_groups: Optional[Dict[str, FieldGroup]] = None` |
| `TemplateCreate` | same |
| `TemplateUpdate` | same |
| `BatchCreate` | same |
| `BatchConfig` | same |

`ResultPatch` gains (all optional, so every existing call site is unaffected):

```python
    group: Optional[str] = None          # group label, when patching a group child
    index: Optional[int] = None          # 0-based entry index within the group
    group_op: Optional[str] = None       # "add" | "remove" | "move"
    to_index: Optional[int] = None       # target index for "move"
```

`ExtractionResult` is **unchanged** (decision R2).

### 2.2 `app/services/ocr_engine.py`

| Function | Change |
|---|---|
| `_output_contract_block` | Accept `field_groups`. Render groups as an array-of-objects illustration and append the group instruction block (§5). |
| `_generate_prompt` | Accept and forward `field_groups`. Render group entries in the numbered field list with their description. |
| `_split_extraction` | Extend the confidence key filter to accept flattened group-child keys (§6). Field values are already passed through untouched. |
| `_process_card_sync` | After splitting: for every defined group, normalise the raw value (§7) and replace it with the canonical JSON string. Record group validation outcomes. Accept `field_groups`. |
| `_call_vlm_api_resilient` | Accept and forward `field_groups` to `_generate_prompt`. |
| `process_batch` | Accept `field_groups` and pass it to `_process_card_sync` through the existing thread-pool submit. |

`_validate_extraction` is left alone: it only inspects `settings.FIELD_KEYS`, never template fields, so a group value cannot reach it.

### 2.3 New module `app/services/validation/groups.py`

```python
def normalise_group(raw: Any, group: FieldGroup) -> tuple[list[dict], list[str]]:
    """Coerce a VLM group value into a safe, canonical list of child dicts.

    Returns (items, problems). Never raises. See §7 for the full rule set.
    """
```

### 2.4 `app/services/validation/runner.py`

- Skip group labels when applying scalar `field_rules` (a regex would otherwise
  match against JSON text).
- Accept flattened child keys in `field_rules`, so `Titel_Tracks[].Spieldauer`
  style per-child rules become possible later. **Not required for v1** — v1 only
  needs the skip, plus merging the group-shape outcomes produced by
  `normalise_group`.

### 2.5 `app/services/template_service.py`

`create_template` / `update_template` persist and round-trip `field_groups`.
Existing sparse template entries continue to load (Pydantic defaults fill `None`).

### 2.6 `app/services/batch_manager.py`

`create_batch` accepts `field_groups` and writes it into the batch's
`config.json`, alongside `fields`, `field_rules` and `authority_bindings`.

### 2.7 `app/api/api_v1/endpoints/batches.py`

- `create_batch` endpoint: serialise nested `FieldGroup` models to plain dicts
  for JSON-safe storage, mirroring the existing `field_rules` / `authority_bindings`
  handling.
- `run_ocr_task`: read `field_groups` from `config.json` and pass it to
  `process_batch`.
- `patch_result`: implement the group-aware branch (§8.2). Existing scalar
  behaviour is untouched when `patch.group is None`.
- `get_batch_config`: return `field_groups` so the frontend can render groups.

### 2.8 `app/api/api_v1/endpoints/templates.py`

No change expected — the router passes whole Pydantic models through.
Verify during implementation.

---

## 3. Exact frontend changes

### 3.1 New files

| File | Purpose |
|---|---|
| `features/configure/RepeatableGroupEditor.tsx` | Create/edit a group: name, description, child fields (add, name, describe, reorder, remove) |
| `features/verify/RepeatableGroupPane.tsx` | Curator editing of group entries in the Verify cockpit |
| `features/results/groupValue.ts` | Shared parse/serialise/effective-value helpers for the JSON-string wire format |

### 3.2 Changed files

| File | Change |
|---|---|
| `store/wizardStore.ts` | `MetadataField` gains `group?: FieldGroupDef \| null`. New actions: `addGroup`, `updateGroup`, `addGroupChild`, `updateGroupChild`, `moveGroupChild`, `removeGroupChild`. `ResultRow` unchanged (values stay strings). |
| `api/templatesApi.ts` | `Template` interface gains `field_groups`; create/update mutations pass it through |
| `api/batchesApi.ts` | `FieldGroup` / `GroupChild` types; `ResultPatch` payload gains `group`, `index`, `group_op`, `to_index` |
| `features/configure/FieldManager.tsx` | "Add repeatable group" action; render groups visually distinct from scalar fields (§3.3); include `field_groups` when saving a template |
| `features/verify/FieldsPane.tsx` | Delegate group labels to `RepeatableGroupPane` instead of rendering a single `EditableCell` |
| `features/results/ResultsTable.tsx` | Render a group cell as a compact summary (`n Einträge`), not raw JSON |
| `features/clean/CleanStep.tsx` | Exclude group labels from the column derivation (a JSON string is not a cleanable column) |
| `features/results/useResultsExport.ts` | Group columns in the client-side CSV, matching §9 exactly |

### 3.3 Template editor presentation

The UI must clearly distinguish the two shapes:

```
▸ Bestellnummer                         (normal field)
▸ Gesamttitel                           (normal field)
▾ Titel_Tracks            [Gruppe · max. 20]
    ├─ Lfd_Nr
    ├─ Titel
    └─ Spieldauer
▸ Gesamtspieldauer                      (normal field)
```

Group rows carry a distinct icon and an indented child list with per-child
reorder (up/down) and remove controls.

---

## 4. Persistence and wire format

### 4.1 Template (`data/templates.json`)

```jsonc
{
  "id": "…",
  "name": "AMIGA Tonband-Karteikarte",
  "fields": ["Bestellnummer", "Tonband_Nr", "Gesamttitel",
             "Titel_Tracks",                       // ← group label, in place
             "Gesamtspieldauer", "…"],
  "field_groups": {
    "Titel_Tracks": {
      "description": "Einzeltitel des Tonbands mit je zugehöriger Spieldauer.",
      "max_items": 20,
      "fields": [
        {"name": "Lfd_Nr",     "description": "Laufende Nummer der Zeile."},
        {"name": "Titel",      "description": "Einzeltitel dieser Zeile."},
        {"name": "Spieldauer", "description": "Spieldauer genau dieser Zeile."}
      ]
    }
  }
}
```

The group label appearing in `fields` is what keeps prompt generation, CSV column
order and bulk `schema_fields` working unchanged.

### 4.2 Result / checkpoint (`data/batches/<batch>/checkpoint.json`)

```jsonc
{
  "filename": "IMG_0001.JPG",
  "success": true,
  "data": {
    "Gesamttitel": "Gershwin - Evergreens",
    "Titel_Tracks": "[{\"Lfd_Nr\":\"1\",\"Titel\":\"The Man I Love\",\"Spieldauer\":\"3'21\"},…]",
    "Gesamtspieldauer": "10'15",
    "Datei": "IMG_0001.JPG", "Batch": "…"
  },
  "edited_data": {
    "Titel_Tracks": "[{\"Lfd_Nr\":\"1\",\"Titel\":\"The Man I Love\",\"Spieldauer\":\"3'21\"},…]"
  },
  "confidence": {
    "Gesamttitel": 0.94,
    "Titel_Tracks[0].Titel": 0.95,
    "Titel_Tracks[0].Spieldauer": 0.88
  },
  "validation": {
    "Titel_Tracks": {"status": "valid", "rule_failed": null, "…": null}
  }
}
```

**Canonical serialisation** (required for deterministic CSV and stable diffs):

```python
json.dumps(items, ensure_ascii=False, separators=(",", ":"))
```

with every item containing **exactly** the defined child names, in the template's
child order. Re-serialising the same logical value therefore produces byte-identical
output.

### 4.3 Why the whole edited array, not per-child edited keys

Per-child edited keys (`edited_data["Titel_Tracks[0].Titel"]`) would satisfy
independent edits, but structural operations have no representation: adding or
removing an entry would need index rewriting across every existing key, and a
removed entry would leave orphans. Storing the effective edited array is
self-consistent, keeps `Dict[str, str]`, and makes the CSV `_edited` columns a
straight positional read. The **API** remains per-child, so callers never send a
whole array.

**Effective value rule**, used everywhere (CSV, Verify, table summaries):

```
effective(group) = parse(edited_data[group])  if present and parseable
                   else parse(data[group])    if present and parseable
                   else []
```

---

## 5. Prompt-generation changes

`_output_contract_block` renders groups inside the existing contract:

```
**AUSGABEFORMAT:** Antworte NUR mit einem validen JSON-Objekt in genau dieser Struktur:
{
  "fields": {
    "Gesamttitel": "…",
    "Titel_Tracks": [ { "Lfd_Nr": "…", "Titel": "…", "Spieldauer": "…" } ],
    "Gesamtspieldauer": "…"
  },
  "confidence": { … },
  "confidence_overall": <Zahl 0.0–1.0>
}
```

Followed by a group instruction block, once per group:

> **Wiederholbare Gruppe „Titel_Tracks"** — *{group description}*
> - Es können **keine, eine oder mehrere** Einträge vorhanden sein.
> - Extrahiere **jeden sichtbaren Eintrag**, auch wenn es viele sind.
> - Bewahre die **Reihenfolge des Dokuments**.
> - Werte, die visuell zur **selben Zeile** gehören, müssen im selben Objekt bleiben.
> - Fasse **niemals mehrere Einträge zu einem zusammen**.
> - Fehlt ein Kindwert, lass ihn **leer** (`""`) — verschiebe **nicht** die folgenden Werte nach oben.
> - **Erfinde keine Einträge.** Gib nur zurück, was auf der Karte steht.

Plus a template-independent disambiguation block emitted whenever a group child
shares a name stem with a scalar field — for AMIGA this yields:

> - `Gesamttitel` ist der **Sammel-/Gesamttitel des Tonbands**, nicht ein Einzeltitel.
> - `Titel_Tracks[*].Titel` sind die **Einzeltitel**. Ein vorhandener Gesamttitel darf
>   **niemals** dazu führen, dass Einzeltitel weggelassen werden.
> - `Gesamtspieldauer` ist die **Gesamtdauer des Tonbands**.
> - `Titel_Tracks[*].Spieldauer` ist die Dauer **genau dieser einen Zeile**. Eine
>   vorhandene Gesamtspieldauer darf **niemals** dazu führen, dass Einzeldauern
>   weggelassen werden.
> - **Berechne oder schätze keine fehlenden Dauern.**

The confidence contract is extended to mention the flattened child key form
(§6), so a compliant model can report per-child confidence.

---

## 6. Confidence handling

Wire format from the model, inside the existing `confidence` map:

```
"Titel_Tracks[0].Titel": 0.95
"Titel_Tracks[0].Spieldauer": 0.88
```

`_split_extraction` currently drops any key not present in `fields` — verified.
Extend the filter: a key is retained when it is either a known field label **or**
matches

```
^(?P<group>[^\[\]]+)\[(?P<index>\d+)\]\.(?P<child>.+)$
```

with `group` a defined group label and `child` a defined child name. Values are
coerced and clamped to `[0, 1]` by the existing `_coerce_confidence`.

A group label may also carry a single group-level confidence
(`"Titel_Tracks": 0.8`); it is retained as today and shown as a group header
badge.

Absent per-child confidence is normal (many models will not report it) and must
render as "no badge", exactly as scalar fields do today.

The CSV `_confidence` column for a child reads
`confidence["<group>[<i>].<child>"]`, converted with the existing percentage
helper.

---

## 7. Validation behaviour

`normalise_group(raw, group)` rules, in order. It **never raises**:

| Input | Result | Recorded problem |
|---|---|---|
| `list` of `dict` | Items normalised (see below) | — |
| `None` / key absent | `[]` | — (an empty group is legitimate) |
| `[]` | `[]` | — |
| JSON **string** containing an array | Parsed, then normalised | `group_was_string` |
| `dict` (model collapsed many→one) | Wrapped as a single item | `group_was_object` |
| `list` with non-dict elements | Non-dict elements dropped | `non_object_item` |
| Any other type | `[]` | `group_malformed` |
| Unparseable JSON string | `[]` | `group_malformed` |

Per item: keep **only** defined child names, in template child order; missing
children become `""`; every value coerced to `str` (`None` → `""`); unexpected
keys are **dropped and counted** (never promoted into the schema). An item that
is entirely empty after normalisation is dropped, so a trailing blank row on a
card does not create a phantom entry.

Outcome recording, using the existing `ValidationOutcome` shape under
`validation[groupLabel]`:

- no problems → `{"status": "valid"}`
- problems → `{"status": "invalid", "rule_failed": "group_shape", "rationale": "<problem codes + counts>"}`

`rationale` carries **problem codes and counts only** — never extracted card
content, so general audit rules are respected. The raw value is preserved where
it already lives (the checkpoint's `data`), which is the application's existing
debugging surface; nothing new is written to the audit log.

Malformed output therefore yields a successfully processed card with an empty
group and a visible `invalid` badge — no batch failure (R7).

---

## 8. Verify / Clean editing behaviour

### 8.1 Verify UI

`RepeatableGroupPane` renders:

```
Titel / Tracks                                    3 Einträge   [+ Eintrag]

#1                                          [↑] [↓] [✕]
  Lfd. Nr.      1
  Titel         The Man I Love          92%
  Spieldauer    3'21                    88%

#2                                          [↑] [↓] [✕]
  Lfd. Nr.      2
  Titel         I Got Rhythm            95%
  Spieldauer    2'48                    —
```

Reuses `EditableCell` for every child value, `CockpitBadge` for validation state
and the existing `confidenceClasses` / `confidencePct` helpers. Edits go through
the same 300 ms debounced PATCH pattern already used for scalar fields.

### 8.2 PATCH semantics (`patch_result`)

When `patch.group is None` the existing scalar behaviour applies **unchanged**.
When `patch.group` is set, the endpoint resolves the effective array (§4.3),
applies one operation, re-serialises canonically into
`edited_data[group]`, and writes the checkpoint with the existing shared writer:

| Payload | Operation |
|---|---|
| `{group, index, field, value}` | Set one child value in entry `index` |
| `{group, group_op: "add", index?}` | Insert an empty entry at `index` (default: append) |
| `{group, group_op: "remove", index}` | Remove entry `index` |
| `{group, group_op: "move", index, to_index}` | Move entry `index` to `to_index` |

Guards: unknown group → `400`; `index` out of range → `400`; `add` beyond
`max_items` → `400` with a message naming the limit. Nothing is ever silently
truncated.

Audit: each operation may carry the existing optional `audit_entry`, appended to
the checkpoint's `audit` list by the existing mechanism. The frontend emits one
per structural change, following the label convention already used by Clean's
bulk transforms (e.g. `op: "group-add"`, `column: "Titel_Tracks"`,
`label: "Eintrag #3 hinzugefügt"`).

### 8.3 Clean

Group labels are **excluded** from Clean's column derivation: a JSON string is not
a meaningful target for column-wise clustering, faceting or regex replacement.
Group children are edited in Verify. This is a documented limitation (§14), not
an oversight — column-wise cleaning of repeated children would need Clean to
operate on a long-format projection, which is out of scope.

---

## 9. CSV representation

**One row per source card.** A group at position *k* in `fields` expands **in
place** at that position, so column order stays deterministic and template-driven.

For a group `G` with children `c1…cm` and `max_items = N`:

```
G_count,
G_1_c1_ocr, G_1_c1_edited, G_1_c1_confidence,
G_1_c2_ocr, G_1_c2_edited, G_1_c2_confidence,
…
G_N_cm_ocr, G_N_cm_edited, G_N_cm_confidence,
G_overflow_json
```

Column count per group: `1 + (N × m × 3) + 1`. For AMIGA `Titel_Tracks`
(`N = 20`, `m = 3`) that is **182 columns** for the group.

Cell semantics:

| Column | Value |
|---|---|
| `G_count` | The **real** total number of entries, even when it exceeds `N` |
| `G_i_c_ocr` | Child `c` of entry `i` from `data[G]`; empty when the entry does not exist |
| `G_i_c_edited` | Child `c` of entry `i` from `edited_data[G]`; empty when unedited |
| `G_i_c_confidence` | `confidence["G[i-1].c"]` as a whole percentage; empty when absent |
| `G_overflow_json` | Canonical JSON array of entries `N+1 …` when `count > N`; otherwise empty |

Rules:

- Entries beyond `max_items` are **never silently discarded** — they are preserved
  verbatim in `G_overflow_json`, and `G_count` states the truth.
- A missing child value is an **empty cell**. Nothing shifts.
- **No duration is calculated or inferred.** An empty `Spieldauer` stays empty.
- Existing conventions unchanged: UTF-8 BOM, CRLF, every cell quoted, `"` doubled.
- Scalar fields keep their existing triplet columns byte-for-byte.

Applies identically to the client-side export
(`features/results/useResultsExport.ts`) and the server-side bulk export
(`app/services/bulk_export.py`). The two must produce the same header for the
same template — a test asserts this.

The `_entries` (multi-entry) path is untouched. When a card carries **both**
`_entries` and a group, `_entries` takes precedence and groups are ignored for
that card (documented limitation, §14; the Findmittel and AMIGA card shapes do
not overlap in practice).

---

## 10. Bulk Processing compatibility

- `bulk_manager.create_run` gains a `field_groups` parameter and freezes it into
  `run.json` next to the existing frozen `schema_fields`, `prompt_template`,
  `field_rules` and `authority_bindings`. **`schema_fields` stays the flat label
  list** — the group label is already in it.
- `endpoints/bulk.py` `create_run` reads `field_groups` from the selected template
  and passes it through. The frozen copy is what the export uses, so editing the
  template mid-run cannot change the CSV shape.
- `bulk_import.materialise_folder` forwards `field_groups` into the generated
  batch's `config.json`, so `run_ocr_task` picks it up with no bulk-specific code.
- `bulk_export.consolidated_header` / row builders implement §9. Generation stays
  **streaming and bounded-memory**: `max_items` comes from the frozen definition,
  so no pre-pass over the collection is needed.
- `failures.csv` is unchanged.
- **Checkpoint/resume semantics are unchanged.** Resume is filename-based; a card
  recorded as successful is never re-processed. Group data lives inside the same
  checkpoint rows.
- **Source provenance is unchanged**: `bulk_run_id`, `source_folder`,
  `source_filename`, `batch_id` still lead every row.
- **No Bulk-specific extraction engine or group semantics.**

---

## 11. AMIGA example template

Seeded as `AMIGA Tonband-Karteikarte` (the existing 40-field
`AMIGA Tonbandkartei` template is **left in place** — see §13).

Field identifiers follow the **existing convention**: the string in `fields` is
both the identifier and the display label. No `field_labels` side-map and no new
identifier abstraction is introduced (operator decision). The names below are
therefore used verbatim as labels.

`fields`, in order:

```
Bestellnummer
Tonband_Nr
Gesamttitel
Titel_Tracks                      ← repeatable group, max_items = 20
Gesamtspieldauer
Sperrvermerk
Ort_der_Aufnahme
Aufnahmedatum
Aufnahmeleiter
Tonmeister
Aufnahmetechniker
Kuenstlerische_Freigabe_Datum
Kuenstlerische_Freigabe_Gez
Technische_Freigabe_Datum
Technische_Freigabe_Gez
Sicherheitsumschnitt_Datum
Sicherheitsumschnitt_Von
Bemerkungen
Orchester
Dirigent_Orchester
Chor
Dirigent_Chor
Solisten
Komponist
Textdichter
Bearbeiter
Verlag
```

`field_groups`:

```jsonc
"Titel_Tracks": {
  "description": "Die Einzeltitel des Tonbands, je Zeile mit zugehöriger Spieldauer.",
  "max_items": 20,
  "fields": [
    {"name": "Lfd_Nr",     "description": "Laufende Nummer der Zeile, falls angegeben."},
    {"name": "Titel",      "description": "Der Einzeltitel dieser Zeile — nicht der Gesamttitel."},
    {"name": "Spieldauer", "description": "Die Spieldauer genau dieser Zeile — nicht die Gesamtspieldauer."}
  ]
}
```

The pre-existing flat `AMIGA Tonbandkartei` template (40 fields) is
**preserved**; the new one is added alongside under a distinct name, which is the
only distinguishing mechanism used — no deprecation system is introduced
(operator decision).

---

## 12. Regression test matrix

All VLM calls mocked via the established pattern
(`monkeypatch.setattr(ocr_engine, "_call_vlm_api_resilient", …)`). No network,
no Ollama, no OpenRouter.

### `tests/test_repeatable_groups.py`

| # | Case | Assertion |
|---|---|---|
| 1 | **Scalar-only template unchanged** | Prompt, result, checkpoint and CSV byte-identical to pre-feature output |
| 2 | Group with **zero** items | `data[G] == "[]"`, `G_count == "0"`, all group cells empty, no validation error |
| 3 | Group with **one** item | Item in position 1, positions 2…20 empty |
| 4 | Group with **multiple** items | Order preserved, each child in its own column |
| 5 | **Missing duration in the middle** | `Spieldauer` of row 2 empty; rows 3+ durations **not shifted up** |
| 6 | **Malformed** array (string, object, mixed, garbage) | Batch **succeeds**, group empty, `validation[G].status == "invalid"`, `rule_failed == "group_shape"` |
| 7 | Group returned as a **dict** (collapsed) | Wrapped as one item, `group_was_object` recorded |
| 8 | **Unexpected child keys** | Dropped, counted, schema unchanged |
| 9 | **Entirely empty item** | Dropped, no phantom entry |
| 10 | Canonical serialisation | Re-serialising the same logical value is byte-identical |
| 11 | **Confidence preserved** | `Titel_Tracks[0].Titel` survives `_split_extraction`; unknown group/child keys still dropped |
| 12 | Prompt content | Group block present; Gesamttitel/Einzeltitel and Gesamtspieldauer/Einzeldauer disambiguation present; absent for scalar-only templates |
| 13 | **Checkpoint/resume** | Group data survives a resume; a successful card is not re-processed; audit entries survive |

### `tests/test_repeatable_group_patch.py`

| # | Case | Assertion |
|---|---|---|
| 14 | **Verify edit** of one child | Only that child changes; `edited_data[G]` canonical |
| 15 | Independent edits | `Titel_Tracks[1].Titel` and `Titel_Tracks[2].Titel` persist **separately** |
| 16 | **Add** entry | Appended/inserted empty entry; `max_items` exceeded → `400` |
| 17 | **Remove** entry | Removed; following entries shift down; no orphan data |
| 18 | **Reorder** entry | Order changed; values stay with their entry |
| 19 | Audit | Each structural operation appends exactly one audit entry |
| 20 | Guards | Unknown group and out-of-range index → `400`; scalar PATCH path unchanged |

### `tests/test_repeatable_group_export.py`

| # | Case | Assertion |
|---|---|---|
| 21 | Header shape | Exactly `1 + 20×3×3 + 1` group columns, expanded in field position |
| 22 | **CSV round-trip** | `_ocr` from raw, `_edited` from edits, `_confidence` from flattened keys |
| 23 | **Overflow** | 23 items → positions 1–20 filled, `G_count == "23"`, `G_overflow_json` holds items 21–23 losslessly |
| 24 | No inference | Empty `Spieldauer` exported empty; never computed |
| 25 | Determinism | Two exports byte-identical |
| 26 | Client/server parity | Server header equals the documented client header for the same template |

### Extensions to existing suites

| Suite | Added |
|---|---|
| `test_bulk_export.py` | **Bulk consolidated export** with a group: provenance intact, group columns correct, streaming preserved (one checkpoint at a time) |
| `test_bulk_run.py` | `field_groups` frozen in `run.json`; a later template edit does not change the export; resume with groups reprocesses nothing |
| `test_bulk_state.py` | `run.json` still carries no extracted metadata (group defs are schema, not content) |
| `test_checkpoint_compat.py` | Group-bearing checkpoints readable by both formats; no write-on-read |

### AMIGA acceptance test

| # | Case | Assertion |
|---|---|---|
| 27 | **Full AMIGA card** | Gesamttitel + 3 individual titles + 3 individual durations + Gesamtspieldauer all present and correctly separated; the overall title does not suppress individual titles; the overall duration does not suppress individual durations; one CSV row with all values in their own columns |

---

## 13. Migration and backwards compatibility

**No migration required.**

| Concern | Behaviour |
|---|---|
| Existing templates | `field_groups` absent → `None` → every path behaves as today. Stored entries are already sparse (the current AMIGA template has only `id`, `name`, `fields`). |
| Existing results / checkpoints | Untouched. `data` stays `Dict[str, str]`; no key is renamed or removed. Readable by the shared checkpoint reader with no format change. |
| Existing exports | Scalar column layout byte-identical. Group columns only appear for templates that define groups. |
| Existing batches mid-flight | `config.json` without `field_groups` → scalar behaviour on resume. |
| `ExtractionResult` / `BatchProgress` | Unchanged, so no frontend type churn and no risk to the progress path. |
| The existing `AMIGA Tonbandkartei` (40 flat fields) template | **Left in place.** The new template is added alongside as `AMIGA Tonband-Karteikarte`. Batches already produced with the old template keep working. Operators migrate by choosing the new template for new runs. |
| Bulk runs created before the feature | `run.json` without `field_groups` → scalar export path. |

---

## 14. Known limitations

- **Nested groups are not supported.** A group's children are scalar only.
- **Clean does not operate on group children** (§8.3). Curation happens in Verify.
- **`max_items` bounds the CSV width, not the data.** Entries beyond it live in
  `G_overflow_json` and require a JSON-aware consumer. `G_count` always states the
  real total.
- **Group columns make wide CSVs.** AMIGA `Titel_Tracks` alone adds 182 columns;
  the full template exceeds 250. Correct and deterministic, but unwieldy in a
  spreadsheet — the long-format export (§15) is the answer if that becomes a
  problem.
- **Per-child confidence depends on model cooperation.** Many models will not
  report it; absent confidence renders as no badge, exactly like scalar fields.
- **A card carrying both `_entries` and a group** processes `_entries` only (§9).
- **Group-level `field_rules` are not applied** in v1 (a regex over JSON text is
  meaningless). Per-child rules are a designed-for extension, not implemented.
- **No display labels for scalar fields** without an additional `field_labels`
  side-map (§11, §16).
- **XML exporters (LIDO, EAD, MODS, MARC, Dublin Core, Darwin Core) are not
  group-aware** in v1. A group label would surface as a JSON string in a note
  field. Scope-limited deliberately; CSV is the AMIGA target format.

---

## 15. Explicitly out of scope

| Item | Reason |
|---|---|
| **Fixing the Findmittel `_entries` curator-edit defect** | Pre-existing defect, documented as a separate follow-up issue (decision R8). Per-entry edits on `_entries` cards are not durably persisted today: the PATCH carries only `{field, value}`, the backend writes page-level `edited_data[field]`, and the read path shows it on every entry. This feature must **not** refactor that workflow. |
| **Long-format `groups.csv`** | Possible follow-up. The primary export stays one row per source card. |
| **Widening `ExtractionResult.data` to `Dict[str, Any]`** | Rejected (R2). Would propagate into `ResultRow`, all seven XML/CSV exporters, the validation runner and Clean's column derivation. |
| Nested / recursive groups | Not needed by the use case. |
| Group support in the XML exporters | Follow-up if a non-CSV ingest path needs it. |
| Per-child `field_rules` and authority bindings | Designed for, not implemented in v1. |
| Column-wise cleaning of group children | Would require Clean to work on a long-format projection. |
| Any change to PR #5 / the Bulk feature branch | Hard boundary: this is a separate follow-up feature. |

---

## 16. Phased implementation order

Each phase ends green (backend `pytest` · `ruff` · `mypy`; frontend
`lint` · `typecheck` · `build` from phase 8) before the next begins, and each is a
separate atomic commit.

| # | Phase | Commit message |
|---|---|---|
| 1 | Schema, wire format, canonical serialisation, `normalise_group` | `feat(groups): add repeatable-group schema and safe normalisation` |
| 2 | Prompt generation incl. AMIGA disambiguation | `feat(groups): teach the prompt generator repeatable groups` |
| 3 | Confidence flattening in `_split_extraction` | `feat(groups): per-child confidence via flattened keys` |
| 4 | Engine + validation wiring; batch/template persistence | `feat(groups): persist and validate groups end to end` |
| 5 | Group-aware `patch_result` incl. add/remove/move + audit | `feat(groups): curator editing of repeated entries` |
| 6 | Single-batch CSV export (server contract + client parity) | `feat(groups): numbered group columns in CSV export` |
| 7 | Bulk: freeze `field_groups`, consolidated export | `feat(groups): bulk consolidated export with group columns` |
| 8 | Frontend template editor (`RepeatableGroupEditor`) | `feat(groups): repeatable-group editor in the template UI` |
| 9 | Frontend Verify pane, results/Clean adjustments | `feat(groups): edit repeated entries in the Verify cockpit` |
| 10 | AMIGA template seed + documentation | `docs(groups): document repeatable groups and the AMIGA template` |
| 11 | Full verification sweep + handover report | — (no commit; report only) |

Phases 1–7 are backend-only and independently testable; the feature is inert
until a template defines a group.

### Prerequisite — satisfied

PR #5 was merged into `main` on 2026-09-03 (merge commit `673afe4`).
Implementation proceeds on `feat/repeatable-groups`, branched from that merge.

### Resolved decisions (formerly open questions)

1. **Field identifiers / display labels.** No new abstraction. The string in
   `fields` is both identifier and label, matching existing convention. `GroupChild`
   therefore carries `name` + `description` only.
2. **Default `max_items`** for groups created in the UI: **12**. The AMIGA
   `Titel_Tracks` group is the explicit exception at **20**.
3. **Legacy AMIGA template**: preserved, never auto-deleted. The new version is
   distinguished by its name alone; no deprecation system is introduced.

---

## 17. Constraints (non-negotiable)

- Backwards-compatible and **additive** throughout.
- Do **not** introduce a second template system, a second confidence system or a
  second extraction engine.
- Do **not** widen `ExtractionResult.data`.
- Do **not** refactor the `_entries` workflow.
- Do **not** silently flatten a group into an ambiguous string, and never discard
  entries beyond `max_items`.
- Do **not** calculate or infer missing durations.
- Malformed model output must **never** fail a batch.
- Do **not** weaken any existing security hardening or the source-file
  immutability guarantee.
- Do **not** commit to `feat/bulk-processing` or otherwise alter PR #5.
