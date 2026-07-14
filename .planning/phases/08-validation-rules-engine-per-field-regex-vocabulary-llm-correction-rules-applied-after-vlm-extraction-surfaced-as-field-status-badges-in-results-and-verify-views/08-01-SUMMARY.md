---
phase: 08-validation-rules-engine
plan: 01
subsystem: api
tags: [pydantic, json-schema, codegen, typescript, shared-types, validation, field-rules]

# Dependency graph
requires:
  - phase: 03.1
    provides: prompt_template schema-first pattern (JSON Schema -> codegen -> Pydantic mirror -> frontend API copy)
provides:
  - FieldRule and ValidationOutcome data shapes in shared JSON schema (template.schema.json + batch.schema.json)
  - Regenerated generated/ts/index.ts with FieldRule, ValidationOutcome, field_rules, corrector_enabled, corrector_cap, validation
  - Pydantic FieldRule, ValidationOutcome in apps/backend/app/models/schemas.py
  - Extended BatchConfig/BatchCreate (field_rules/corrector_enabled/corrector_cap) and ExtractionResult (validation) in schemas.py
  - Extended Template/TemplateCreate/TemplateUpdate (field_rules) in schemas.py
  - FieldRule and ValidationOutcome interfaces in batchesApi.ts; BatchCreate extended
  - Template extended in templatesApi.ts; mutation signatures accept field_rules
  - ExtractionResult and ResultRow in wizardStore.ts extended with validation field
affects:
  - 08-02 (backend validation engine needs FieldRule/ValidationOutcome Pydantic models)
  - 08-03 (configure ValidationRuleEditor needs FieldRule in frontend types)
  - 08-04 (results badges need ValidationOutcome in ResultRow)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Schema-first extension: JSON Schema definitions -> turbo generate -> manual Pydantic mirror (same as prompt_template Phase 03.1 pattern)"
    - "FieldRule inlined in both schema files for self-contained codegen (no cross-file $ref)"
    - "ValidationOutcome imported via batchesApi.ts re-exported from wizardStore.ts"

key-files:
  created: []
  modified:
    - packages/shared-types/schemas/template.schema.json
    - packages/shared-types/schemas/batch.schema.json
    - packages/shared-types/generated/ts/index.ts
    - packages/shared-types/generated/py/batch.py
    - packages/shared-types/generated/py/template.py
    - apps/backend/app/models/schemas.py
    - apps/frontend/src/api/batchesApi.ts
    - apps/frontend/src/api/templatesApi.ts
    - apps/frontend/src/store/wizardStore.ts

key-decisions:
  - "FieldRule duplicated into batch.schema.json (not cross-referenced from template.schema.json) because codegen script is single-file-per-schema; duplicate is silently skipped at generation time"
  - "ValidationOutcome imported in wizardStore.ts via batchesApi.ts re-export to avoid circular imports and keep ExtractionResult/ResultRow consistent with the API layer"
  - "wizardStore.ts ExtractionResult and ResultRow both extended with validation field — rides on existing excluded-from-partialize results array (no localStorage regression)"

patterns-established:
  - "All new fields use null/false/100 defaults — backward compat with existing batches/templates that lack these keys"
  - "Frontend API type copies (batchesApi.ts, templatesApi.ts) are manually maintained and not auto-synced with codegen — must be updated explicitly for each new field"

requirements-completed: [FR2, FR4]

# Metrics
duration: 3min
completed: 2026-05-18
---

# Phase 8 Plan 01: Schema Foundation Summary

**FieldRule and ValidationOutcome JSON Schema definitions + Pydantic/TypeScript propagation following the prompt_template schema-first pattern**

## Performance

- **Duration:** 3 min
- **Started:** 2026-05-18T12:10:28Z
- **Completed:** 2026-05-18T12:13:37Z
- **Tasks:** 2
- **Files modified:** 9

## Accomplishments
- Added `FieldRule` (preset_id, pattern, vocabulary, fuzzy_distance, corrector_enabled) and `ValidationOutcome` (status enum, rule_failed, original_value, rationale, corrector_proposal) to JSON schema files and ran `turbo generate` — all new interfaces appear in `generated/ts/index.ts`
- Mirrored both types as Pydantic `BaseModel` classes in `schemas.py` and extended `BatchConfig`, `BatchCreate`, `ExtractionResult`, `Template`, `TemplateCreate`, `TemplateUpdate` with backward-compatible null/false/100 defaults
- Propagated `FieldRule`/`ValidationOutcome` to frontend local API type copies (`batchesApi.ts`, `templatesApi.ts`) and extended `ExtractionResult`/`ResultRow` in `wizardStore.ts` — TypeScript compiles cleanly, Python smoke test passes

## Task Commits

1. **Task 1: Extend JSON schemas with FieldRule + ValidationOutcome and run codegen** - `5dc6333` (feat)
2. **Task 2: Mirror schema in Pydantic schemas.py and frontend API type copies** - `d5a48e3` (feat)

## Files Created/Modified
- `packages/shared-types/schemas/template.schema.json` - Added FieldRule definition; added field_rules to Template/TemplateCreate/TemplateUpdate
- `packages/shared-types/schemas/batch.schema.json` - Added FieldRule (inlined) + ValidationOutcome definitions; extended BatchConfig/BatchCreate with field_rules/corrector_enabled/corrector_cap; extended ExtractionResult with validation
- `packages/shared-types/generated/ts/index.ts` - Regenerated: FieldRule, ValidationOutcome interfaces; updated BatchConfig/BatchCreate/ExtractionResult/Template/TemplateCreate/TemplateUpdate
- `packages/shared-types/generated/py/batch.py` - Regenerated Pydantic for batch schema
- `packages/shared-types/generated/py/template.py` - Regenerated Pydantic for template schema
- `apps/backend/app/models/schemas.py` - Added FieldRule, ValidationOutcome classes; extended BatchConfig/BatchCreate/ExtractionResult/Template/TemplateCreate/TemplateUpdate
- `apps/frontend/src/api/batchesApi.ts` - Added FieldRule/ValidationOutcome interfaces; extended BatchCreate
- `apps/frontend/src/api/templatesApi.ts` - Re-exported FieldRule from batchesApi; extended Template interface and mutation signatures
- `apps/frontend/src/store/wizardStore.ts` - Imported ValidationOutcome; extended ExtractionResult and ResultRow with validation field

## Decisions Made
- Duplicated `FieldRule` into `batch.schema.json` rather than using a cross-file `$ref` — the codegen script processes one file at a time and does not resolve cross-file references. The duplicate is silently skipped at generation time (logged as "Skipping duplicate: FieldRule"), so the generated output has exactly one `FieldRule` interface.
- `ValidationOutcome` imported in `wizardStore.ts` via a re-export from `batchesApi.ts` to avoid circular imports while keeping the `ExtractionResult` and `ResultRow` consistent with the API layer type.

## Deviations from Plan

**1. [Rule 2 - Missing Critical] Extended wizardStore.ts ExtractionResult and ResultRow with validation field**
- **Found during:** Task 2 (frontend API type copies)
- **Issue:** Plan specified updating `batchesApi.ts` and `templatesApi.ts` but `ExtractionResult` (used throughout the app including ResultRow) is defined in `wizardStore.ts` and imported by `batchesApi.ts`. Without extending the store type, the validation field would silently be dropped at the hydration boundary.
- **Fix:** Added `validation?: Record<string, ValidationOutcome> | null` to both `ExtractionResult` and `ResultRow` in `wizardStore.ts`; re-exported `ValidationOutcome` from there.
- **Files modified:** `apps/frontend/src/store/wizardStore.ts`
- **Verification:** TypeScript `--noEmit` passes cleanly; validation field visible in both interfaces
- **Committed in:** `d5a48e3` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 2 - missing critical)
**Impact on plan:** Necessary for correctness — without the wizardStore extension, validation data would be silently discarded during results hydration. No scope creep.

## Issues Encountered
None — codegen, Python smoke test, and TypeScript type check all passed on first run.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Schema foundation complete; 08-02 (backend validation engine) and 08-03 (Configure rule editor) can proceed in parallel
- `FieldRule` and `ValidationOutcome` are available in all layers: Pydantic models, generated TypeScript, and frontend API type copies
- Backward compatibility confirmed: existing batches/templates without field_rules/validation keys deserialize without error

---
*Phase: 08-validation-rules-engine*
*Completed: 2026-05-18*
