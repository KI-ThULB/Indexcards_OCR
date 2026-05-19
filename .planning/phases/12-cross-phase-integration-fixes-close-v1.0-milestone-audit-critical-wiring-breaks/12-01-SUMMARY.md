---
phase: 12-cross-phase-integration-fixes-close-v1.0-milestone-audit-critical-wiring-breaks
plan: 01
subsystem: api, database
tags: [template-service, authority-bindings, edited-data, pydantic, json-schema, codegen, persistence]

# Dependency graph
requires:
  - phase: 11-authority-reconciliation
    provides: authority_bindings fields on TemplateCreate/TemplateUpdate/Template Pydantic models; AuthorityBinding schema type
  - phase: 09-verification-cockpit
    provides: PATCH endpoint that writes edited_data to checkpoint.json; ExtractionResult shape in JSON Schema

provides:
  - authority_bindings round-trip through template save/load (create_template constructor + update_template is-not-None guard)
  - edited_data typed field in batch.schema.json ExtractionResult (Dict[str,str]|null, default null)
  - edited_data typed field in schemas.py ExtractionResult Pydantic model (Optional[Dict[str,str]] = None)
  - regenerated packages/shared-types/generated/ts/index.ts with edited_data in ExtractionResult interface

affects: [12-04-plan, wave-2-frontend-hydration, FR2, FR5, authority-persistence, curator-edit-round-trip]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "authority_bindings forwarding: same constructor-kwarg + is-not-None-guard pattern as prompt_template fix in Phase 03.1 Plan 03"
    - "authority_bindings serialization in update_template: v.dict() if hasattr(v,'dict') else v — same as create_batch in batches.py"
    - "edited_data: Optional[Dict[str,str]] = None pattern for additive backward-compatible Pydantic field extension"
    - "JSON Schema anyOf null-union pattern for optional dict fields: anyOf:[{additionalProperties:{type:string},type:object},{type:null}]"

key-files:
  created: []
  modified:
    - apps/backend/app/services/template_service.py
    - packages/shared-types/schemas/batch.schema.json
    - apps/backend/app/models/schemas.py
    - packages/shared-types/generated/ts/index.ts
    - packages/shared-types/generated/py/__init__.py

key-decisions:
  - "authority_bindings in create_template() uses constructor kwarg (no manual serialization) — Template Pydantic model handles serialization via .dict() call on line 50"
  - "authority_bindings in update_template() serializes values with v.dict() if hasattr(v,'dict') else v — same pattern as create_batch batches.py, required because update_template writes to raw JSON dict not Pydantic model"
  - "edited_data added ONLY to ExtractionResult in JSON Schema — AuditEntry/ResultPatch/AuthorityBinding/ReconciliationOutcome deferred to Phase 13 (codegen pipeline re-adoption)"
  - "turbo generate is NOT the codegen command — actual script is node scripts/generate.mjs inside packages/shared-types"

patterns-established:
  - "Gap-closure pattern: late-phase field additions to service layer follow constructor-kwarg (create) + is-not-None-guard (update) convention"
  - "JSON Schema scope boundary: Phase 12 edits only edited_data; Phase 13 will add AuditEntry/ResultPatch/AuthorityBinding/ReconciliationOutcome"

requirements-completed:
  - FR2
  - FR5

# Metrics
duration: ~8min
completed: 2026-05-19
---

# Phase 12 Plan 01: Backend Foundation Fixes Summary

**authority_bindings forwarded through template_service create/update (FR2 gap closed) and edited_data added to ExtractionResult JSON Schema + Pydantic model with codegen regeneration (FR5 schema foundation)**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-05-19T05:15:05Z
- **Completed:** 2026-05-19T05:23:00Z
- **Tasks:** 2
- **Files modified:** 4 (template_service.py, batch.schema.json, schemas.py, generated/ts/index.ts)

## Accomplishments

- Fixed create_template() to pass authority_bindings to Template constructor kwarg — save-then-reload now preserves Phase 11 authority configurations
- Fixed update_template() to serialize and store authority_bindings with is-not-None guard using same v.dict() pattern as create_batch endpoint in batches.py
- Added edited_data property to ExtractionResult in batch.schema.json (anyOf:[object|null], default null)
- Added edited_data: Optional[Dict[str, str]] = None to ExtractionResult Pydantic model — backward-compat (existing checkpoint.json rows without field deserialize cleanly)
- Ran node scripts/generate.mjs — edited_data appears as `edited_data?: { [k: string]: string } | null` in ExtractionResult interface in generated/ts/index.ts
- No Phase 13 scope (AuditEntry/ResultPatch/AuthorityBinding/ReconciliationOutcome) added to JSON Schema

## Task Commits

Each task was committed atomically:

1. **Task 1: Fix 1 — template_service forwards authority_bindings in create_template and update_template** - `696d017` (fix)
2. **Task 2: Fix 4a/4b — add edited_data to JSON Schema ExtractionResult + Pydantic model + regenerate codegen** - `50587cd` (fix)

**Plan metadata:** pending (docs: complete plan)

## Files Created/Modified

- `apps/backend/app/services/template_service.py` - Added authority_bindings kwarg to create_template() constructor; added is-not-None guard block in update_template() after field_rules branch
- `packages/shared-types/schemas/batch.schema.json` - Added edited_data property to ExtractionResult.properties after validation block
- `apps/backend/app/models/schemas.py` - Added edited_data: Optional[Dict[str, str]] = None to ExtractionResult Pydantic model
- `packages/shared-types/generated/ts/index.ts` - Regenerated; edited_data appears in ExtractionResult interface

## Decisions Made

- authority_bindings in create_template() passes directly to Template constructor — no manual serialization needed because `templates.append(new_template.dict())` on the next line handles it via Pydantic
- authority_bindings in update_template() requires explicit dict serialization because update_template writes directly to raw JSON dict (not a Pydantic object) — applies `v.dict() if hasattr(v, "dict") else v` matching the batches.py create_batch pattern
- edited_data JSON Schema scope kept tight: only the one new property on ExtractionResult; AuditEntry/ResultPatch/AuthorityBinding/ReconciliationOutcome deferred to Phase 13

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Identified correct codegen command (node scripts/generate.mjs, not npx turbo generate)**

- **Found during:** Task 2 (Step C — Run codegen)
- **Issue:** Plan's action said `npx turbo generate`; this launches an interactive Turborepo generator wizard (prompts for adding a config file) — wrong command for JSON Schema → TypeScript codegen in this project
- **Fix:** Killed the interactive process, checked packages/shared-types/package.json, found the actual script is `node scripts/generate.mjs` in the shared-types package
- **Files modified:** None (command correction only)
- **Verification:** `node scripts/generate.mjs` ran non-interactively, printed "Generation complete." and "Written: generated/ts/index.ts (15 interfaces)"; `grep edited_data` confirmed field in output
- **Committed in:** 50587cd (Task 2 commit includes the correctly regenerated generated/ts/index.ts)

---

**Total deviations:** 1 auto-fixed (Rule 3 - blocking: wrong codegen command in plan)
**Impact on plan:** Fix required to complete Task 2. No scope creep — same output, different invocation path.

## Issues Encountered

- `npx turbo generate` is an interactive wizard that prompts for adding a Turborepo custom generator config file — not the JSON Schema codegen command. The actual codegen is `node scripts/generate.mjs` in packages/shared-types (defined in `package.json` scripts.generate). This was discovered immediately and resolved without retrying.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Fix 1 (FR2): authority_bindings round-trips through template save/load; downstream ConfigureStep.ReconcilePane and URI emission path now see bindings on reload
- Fix 4a/4b schema foundation: edited_data is a typed field in JSON Schema + Pydantic ExtractionResult; Wave 2 Plan 12-04 can safely add the frontend TS type and hydration merge
- Wave 2 plans (12-02, 12-03, 12-04) have no schema dependencies blocking them; 12-04 depends on this plan's schema foundation landing (which it now has)
- Python imports cleanly; JSON Schema is valid JSON; codegen pipeline produces 15 interfaces including updated ExtractionResult

---
*Phase: 12-cross-phase-integration-fixes-close-v1.0-milestone-audit-critical-wiring-breaks*
*Completed: 2026-05-19*
