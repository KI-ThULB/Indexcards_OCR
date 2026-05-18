---
phase: 11-authority-reconciliation
plan: 01
subsystem: api
tags: [json-schema, pydantic, fastapi, typescript, authority-reconciliation, gnd, wikidata, geonames, aat]

# Dependency graph
requires:
  - phase: 08-validation-rules-engine
    provides: "FieldRule pattern + ValidationOutcome schema + batchesApi.ts type-copy pattern"
  - phase: 10-openrefine-cleaning-stage
    provides: "AuditEntry schema + ResultPatch + PATCH endpoint + batch config.json read/write"
provides:
  - "ReconciliationOutcome and AuthorityBinding in JSON Schema + generated TS types"
  - "ValidationOutcome.reconciliation optional field in all type layers"
  - "ResultPatch.clear_reconciliation: bool = False for null-vs-omitted safe clearing"
  - "authority/cache.py with atomic write, empty-array no-match semantics, clear_cache"
  - "POST /api/v1/reconcile stub endpoint with per-batch cache lookup"
  - "DELETE /api/v1/batches/{batch_name}/authority-cache endpoint"
  - "GEONAMES_USERNAME in config.py settings"
  - "batch_manager.create_batch() snapshots authority_bindings alongside field_rules"
  - "Frontend: ReconciliationOutcome, AuthorityType, AuthorityBinding types in batchesApi.ts"
  - "Frontend: postReconcile() API function"
  - "Frontend: MetadataField.authority and updateFieldAuthority action in wizardStore"
  - "Frontend: TemplateSelector hydrates authority_bindings from template"
affects: [11-02, 11-03, 11-04, 11-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "clear_reconciliation: bool flag for null-vs-omitted disambiguation (version-independent Pydantic pattern)"
    - "Atomic tmp-file rename for concurrent cache writes (tmp.replace(p))"
    - "Empty-array [] caches 'queried, no results' vs absent key 'never queried'"
    - "Authority package at services/authority/ parallel to services/validation/"
    - "get_settings() function alongside module-level settings singleton for FastAPI Depends injection"

key-files:
  created:
    - apps/backend/app/services/authority/__init__.py
    - apps/backend/app/services/authority/cache.py
    - apps/backend/app/api/api_v1/endpoints/reconcile.py
  modified:
    - packages/shared-types/schemas/template.schema.json
    - packages/shared-types/schemas/batch.schema.json
    - packages/shared-types/generated/ts/index.ts
    - apps/backend/app/models/schemas.py
    - apps/backend/app/core/config.py
    - apps/backend/app/services/batch_manager.py
    - apps/backend/app/api/api_v1/endpoints/batches.py
    - apps/backend/app/api/api_v1/api.py
    - apps/frontend/src/api/batchesApi.ts
    - apps/frontend/src/api/templatesApi.ts
    - apps/frontend/src/store/wizardStore.ts
    - apps/frontend/src/features/configure/TemplateSelector.tsx

key-decisions:
  - "clear_reconciliation: bool = False chosen over Pydantic model_fields_set for null-vs-omitted: version-independent, unambiguous between frontend and backend"
  - "get_settings() factory added to config.py alongside singleton for FastAPI Depends injection"
  - "DELETE /authority-cache placed BEFORE generic /{batch_name} DELETE to prevent path-parameter greedy matching"
  - "authority_bindings serialized to plain dicts in create_batch endpoint (same pattern as field_rules)"
  - "TemplateSelector hydrates authority_bindings back to MetadataField.authority on template select"

requirements-completed: [FR2, FR4]

# Metrics
duration: ~8min
completed: 2026-05-18
---

# Phase 11 Plan 01: Schema + Foundation Summary

**ReconciliationOutcome + AuthorityBinding types in JSON Schema and Pydantic, authority/cache.py with atomic-write semantics, POST /api/v1/reconcile stub, DELETE authority-cache endpoint, GEONAMES_USERNAME, and frontend type copies in batchesApi/templatesApi/wizardStore**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-05-18T15:18:52Z
- **Completed:** 2026-05-18T15:26:10Z
- **Tasks:** 2
- **Files modified:** 13 (3 created, 10 modified)

## Accomplishments
- Extended both JSON Schemas (template + batch) with ReconciliationOutcome, AuthorityBinding, and authority_bindings fields; codegen produces 15 interfaces including both new types
- Created authority/cache.py with read_cache/write_cache_entry/lookup_cache/clear_cache using atomic tmp-file rename; empty-array [] semantics correctly distinguish "queried, no results" from "never queried"
- Wired all 13 type layers: JSON Schema → codegen → Pydantic schemas.py → batches.py endpoints → batch_manager.py → config.py → batchesApi.ts → templatesApi.ts → wizardStore.ts → TemplateSelector.tsx

## Task Commits

1. **Task 1: JSON schemas, codegen, Pydantic, config, batch_manager, cache, endpoints** - `0b73129` (feat)
2. **Task 2: Frontend type copies — batchesApi, templatesApi, wizardStore, TemplateSelector** - `bcc3dcb` (feat)

## Files Created/Modified
- `packages/shared-types/schemas/template.schema.json` — AuthorityBinding definition; authority_bindings on Template/TemplateCreate/TemplateUpdate
- `packages/shared-types/schemas/batch.schema.json` — ReconciliationOutcome + AuthorityBinding definitions; reconciliation on ValidationOutcome; authority_bindings on BatchConfig + BatchCreate
- `packages/shared-types/generated/ts/index.ts` — regenerated with 15 interfaces; ReconciliationOutcome, AuthorityBinding, ValidationOutcome.reconciliation present
- `apps/backend/app/models/schemas.py` — ReconciliationOutcome + AuthorityBinding models; extended ValidationOutcome, ResultPatch (clear_reconciliation), BatchCreate, BatchConfig, Template*
- `apps/backend/app/core/config.py` — GEONAMES_USERNAME: Optional[str] = None; get_settings() function
- `apps/backend/app/services/batch_manager.py` — authority_bindings parameter in create_batch() and config_data
- `apps/backend/app/api/api_v1/endpoints/batches.py` — reconciliation logic in PATCH handler; DELETE /authority-cache endpoint; GET /config returns authority_bindings; authority_bindings serialized in create_batch handler
- `apps/backend/app/api/api_v1/api.py` — reconcile_router registered at /reconcile
- `apps/backend/app/services/authority/__init__.py` — empty package marker
- `apps/backend/app/services/authority/cache.py` — read_cache, write_cache_entry, lookup_cache, clear_cache with atomic tmp-replace
- `apps/backend/app/api/api_v1/endpoints/reconcile.py` — POST /api/v1/reconcile stub with cache lookup
- `apps/frontend/src/api/batchesApi.ts` — ReconciliationOutcome, AuthorityType, AuthorityBinding; extended ValidationOutcome, AuditEntry, BatchCreate, BatchConfig; patchResult with reconciliation params; postReconcile()
- `apps/frontend/src/api/templatesApi.ts` — imports AuthorityBinding from batchesApi; authority_bindings on Template/mutation payloads
- `apps/frontend/src/store/wizardStore.ts` — imports/exports AuthorityBinding; MetadataField.authority; updateFieldAuthority action
- `apps/frontend/src/features/configure/TemplateSelector.tsx` — authority hydration from template.authority_bindings

## Decisions Made
- `clear_reconciliation: bool = False` chosen over Pydantic v2 `model_fields_set` inspection because it is version-independent and unambiguous: `clear_reconciliation=True` always means "clear"; `reconciliation=null` always means "not provided". Works with any Pydantic v1/v2/v3 version.
- `get_settings()` factory function added alongside the module-level `settings` singleton so FastAPI `Depends(get_settings)` can be used in the new DELETE authority-cache endpoint without breaking the existing direct `settings` usage pattern.
- DELETE `/authority-cache` placed strictly BEFORE the generic `/{batch_name}` DELETE route — FastAPI path-parameter greedy matching would otherwise swallow the static "authority-cache" segment.
- `authority_bindings` serialized to plain dicts in the `create_batch` endpoint handler via same `v.dict() if hasattr(v, "dict") else v` pattern as existing `field_rules` serialization.

## Deviations from Plan

None - plan executed exactly as written. The `create_batch` endpoint needed the `authority_bindings` serialization step (parallel to the existing `field_rules` dict conversion) which was implied by the plan and implemented correctly.

## Issues Encountered
None. All 11 verification checks passed on first attempt. TypeScript `--noEmit` produced zero errors after Task 2.

## User Setup Required
None required for this plan. GEONAMES_USERNAME is added to config.py but is optional (None default). Plan 11-02 will document that users wanting GeoNames reconciliation must add `GEONAMES_USERNAME=<account>` to their root `.env` file.

## Next Phase Readiness
- Wave 2 (Plans 11-02 and 11-03) can execute in parallel — both depend only on the foundation types established here
- Plan 11-02 (backend authority clients): services/authority/ package exists, reconcile endpoint stub ready to replace with real dispatch
- Plan 11-03 (Configure AuthorityBindingEditor): MetadataField.authority + updateFieldAuthority + authority_bindings on BatchCreate all in place
- No blockers

---
*Phase: 11-authority-reconciliation*
*Completed: 2026-05-18*
