---
phase: 11-authority-reconciliation
plan: 03
subsystem: frontend-configure
tags: [typescript, react, zustand, authority-reconciliation, configure-step, template, gnd, wikidata, geonames, aat]

# Dependency graph
requires:
  - phase: 11-authority-reconciliation
    plan: 01
    provides: "MetadataField.authority + updateFieldAuthority action + AuthorityBinding types in batchesApi.ts + authority_bindings on BatchCreate/Template + TemplateSelector.authority hydration"
provides:
  - "AuthorityBindingEditor.tsx — 9-option collapsible disclosure per field row in Configure step"
  - "FieldManager renders <AuthorityBindingEditor> per field; handleSaveTemplate serializes authority_bindings"
  - "ConfigureStep.createBatchMutation.mutate carries authority_bindings from Zustand fields"
  - "TemplateSelector already hydrated authority_bindings in Plan 11-01 (confirmed intact)"
affects: [11-04, 11-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Collapsible disclosure pattern for AuthorityBindingEditor matches ValidationRuleEditor (isExpanded + ChevronDown rotate-180)"
    - "authority_bindings serialized as Record<string,AuthorityBinding> keyed by field.label — same pattern as field_rules in FieldManager and ConfigureStep"
    - "Select value='' sentinel for null authority type (HTML select cannot represent null natively)"

key-files:
  created:
    - apps/frontend/src/features/configure/AuthorityBindingEditor.tsx
  modified:
    - apps/frontend/src/features/configure/FieldManager.tsx
    - apps/frontend/src/features/configure/ConfigureStep.tsx

key-decisions:
  - "createBatch authority_bindings wiring lives in ConfigureStep.tsx (not FieldManager.tsx) — this is where createBatchMutation.mutate is called, matching the existing field_rules pattern"
  - "AuthorityBindingEditor uses ChevronDown + rotate-180 collapse (not ChevronRight/ChevronDown swap) — matches ValidationRuleEditor pattern already established in the codebase"
  - "TemplateSelector authority hydration confirmed pre-existing from Plan 11-01 Task 2 — no file change required in this plan"

requirements-completed: [FR2]

# Metrics
duration: ~4min
completed: 2026-05-18
---

# Phase 11 Plan 03: Configure-step AuthorityBindingEditor Summary

**Collapsible AuthorityBindingEditor per FieldManager row with 9-option dropdown (None + 5 GND sub-collections + Wikidata + GeoNames + Getty AAT); authority_bindings serialized in template save and batch create; TemplateSelector hydration confirmed from Plan 11-01**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-05-18T12:30:47Z
- **Completed:** 2026-05-18T12:34:47Z
- **Tasks:** 2
- **Files modified:** 3 created/modified (AuthorityBindingEditor.tsx created; FieldManager.tsx + ConfigureStep.tsx modified)

## Accomplishments

- Created `AuthorityBindingEditor.tsx` — 69-line component following the exact ValidationRuleEditor disclosure pattern (isExpanded state + ChevronDown rotate-180 + border-t divider + bg-parchment-light/20 expanded area); 9 authority options; blue badge when authority set; select value='' sentinel for null type
- Updated `FieldManager.tsx` — imports AuthorityBindingEditor; destructures updateFieldAuthority from useWizardStore; renders `<AuthorityBindingEditor>` after `<ValidationRuleEditor>` per field row; handleSaveTemplate now serializes authority_bindings alongside field_rules
- Updated `ConfigureStep.tsx` — imports AuthorityBinding type; builds authorityBindings Record from Zustand fields; passes authority_bindings to createBatchMutation.mutate (parallel to field_rules)
- Confirmed `TemplateSelector.tsx` already has authority hydration from Plan 11-01 Task 2 — no changes required

## Task Commits

1. **Task 1: AuthorityBindingEditor + FieldManager + ConfigureStep** - `c522869` (feat)
2. **Task 2: TemplateSelector authority hydration** — already implemented in Plan 11-01 commit `bcc3dcb`; verified intact, no changes required

## Files Created/Modified

- `apps/frontend/src/features/configure/AuthorityBindingEditor.tsx` — NEW: 9-option collapsible disclosure; onChange callback emits AuthorityBinding|null; blue badge for active authority
- `apps/frontend/src/features/configure/FieldManager.tsx` — added AuthorityBindingEditor import + render; updateFieldAuthority destructured; handleSaveTemplate serializes authority_bindings
- `apps/frontend/src/features/configure/ConfigureStep.tsx` — AuthorityBinding type imported; authority_bindings built from fields and included in createBatchMutation.mutate payload

## Verification Results

All 5 plan verification checks passed:
1. `AuthorityBindingEditor.tsx` exists
2. `gnd-persons` sub-collection present in AUTHORITY_OPTIONS
3. FieldManager imports/renders AuthorityBindingEditor
4. FieldManager includes authority_bindings serialization
5. TemplateSelector includes authority_bindings hydration
- `tsc --noEmit` produces zero errors

## Deviations from Plan

**[Rule 3 - Blocking issue] createBatch payload lives in ConfigureStep.tsx, not FieldManager.tsx**
- **Found during:** Task 1
- **Issue:** The plan said "The batch creation call may live in ConfigureStep.tsx rather than FieldManager.tsx — check where createBatchMutation is invoked." On inspection, createBatchMutation is called exclusively in ConfigureStep.tsx (not FieldManager.tsx).
- **Fix:** Updated ConfigureStep.tsx instead of FieldManager.tsx for the createBatch authority_bindings wiring. Added ConfigureStep.tsx to files_modified.
- **Files modified:** apps/frontend/src/features/configure/ConfigureStep.tsx
- **Commit:** c522869 (included in Task 1 commit)

**[Confirmation] TemplateSelector already implemented in Plan 11-01**
- Plan 11-01 Task 2 already added `authority: template.authority_bindings?.[label] ?? null` to TemplateSelector.handleSelectTemplate. Task 2 of this plan had nothing to add. Verified clean TypeScript and grep confirm hydration present.

## Issues Encountered

None. TypeScript compiled cleanly after all changes. All verification assertions pass on first attempt.

## Next Phase Readiness

- Wave 3 (Plans 11-04 and 11-05) can now execute
- Plan 11-04 (Clean view ReconcilePane): authority_bindings in batch config.json available via useBatchConfigQuery; updateFieldAuthority action wired; field.authority.type drives reconcilePane visibility
- Plan 11-05 (Export URI emission): ReconciliationOutcome.uri in results data; no Configure-step dependencies
- No blockers

---
*Phase: 11-authority-reconciliation*
*Completed: 2026-05-18*
