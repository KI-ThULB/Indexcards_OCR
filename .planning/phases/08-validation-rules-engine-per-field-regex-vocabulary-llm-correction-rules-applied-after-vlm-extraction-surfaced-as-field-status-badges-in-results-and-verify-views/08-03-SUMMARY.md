---
phase: 08-validation-rules-engine
plan: 03
subsystem: frontend-configure
tags: [zustand, react, validation, field-rules, corrector, template, configure-step]

# Dependency graph
requires:
  - phase: 08-01
    provides: FieldRule and ValidationOutcome types in batchesApi.ts and wizardStore.ts
provides:
  - ValidationRuleEditor disclosure component on each FieldManager field row
  - validationPresets.ts const mirroring backend preset list (13 presets)
  - MetadataField.rule extension in wizardStore.ts
  - correctorEnabled/correctorCap state + updateFieldRule/setCorrectorEnabled/setCorrectorCap/acceptCorrectorProposal/rejectCorrectorProposal actions
  - Batch-level corrector toggle + cap input in ConfigureStep Card 2
  - field_rules/corrector_enabled/corrector_cap sent in createBatch payload
  - field_rules captured in Save Template (via FieldManager.handleSaveTemplate)
  - field_rules restored on template load (via TemplateSelector.handleSelectTemplate)
affects:
  - 08-04 (results badges/filter chips use acceptCorrectorProposal/rejectCorrectorProposal actions)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Collapsible disclosure via isExpanded state + ChevronDown (matches PromptTemplateEditor pattern — no new dependency)"
    - "Controlled ValidationRuleEditor synced from field.rule prop via useEffect for external changes (template load)"
    - "field_rules map keyed by field label — consistent with backend data[field_label] lookup"
    - "correctorEnabled/correctorCap persisted in Zustand partialize (small scalars, safe)"
    - "Template load hydrates MetadataField.rule from template.field_rules by label key"

key-files:
  created:
    - apps/frontend/src/features/configure/validationPresets.ts
    - apps/frontend/src/features/configure/ValidationRuleEditor.tsx
  modified:
    - apps/frontend/src/store/wizardStore.ts
    - apps/frontend/src/features/configure/FieldManager.tsx
    - apps/frontend/src/features/configure/ConfigureStep.tsx
    - apps/frontend/src/features/configure/TemplateSelector.tsx

key-decisions:
  - "ValidationRuleEditor uses isExpanded state + <button> collapse header (same pattern as PromptTemplateEditor, not <details> HTML element) — consistent with existing codebase"
  - "TemplateSelector.handleSelectTemplate refactored to accept full Template object instead of individual args — cleaner signature, enables field_rules hydration without adding more params"
  - "field_rules in Save Template handled in FieldManager.handleSaveTemplate (the actual mutation caller), not in SaveTemplateDialog (which only collects the template name) — no change to SaveTemplateDialog needed"
  - "acceptCorrectorProposal sets validation[field].status to 'valid' AND updates editedData[field] atomically — prevents stale corrected badge after curator accepts"

patterns-established:
  - "Per-field rule editors as disclosures — minimal footprint, collapsed by default, no layout disruption"
  - "FieldRule null = no rule; presetId='none' produces null rule from editor"

requirements-completed: [FR2]

# Metrics
duration: 3min
completed: 2026-05-18
---

# Phase 8 Plan 03: Configure ValidationRuleEditor Summary

**Per-field validation rule editor UI in Configure step with batch-level corrector toggle, template round-trip, and createBatch payload extension**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-05-18T06:36:38Z
- **Completed:** 2026-05-18T06:39:38Z
- **Tasks:** 3
- **Files modified:** 6

## Accomplishments

- Extended `wizardStore.ts` with `MetadataField.rule`, `correctorEnabled`, `correctorCap`, and five new actions (`updateFieldRule`, `setCorrectorEnabled`, `setCorrectorCap`, `acceptCorrectorProposal`, `rejectCorrectorProposal`) — TypeScript compiles cleanly, `partialize` includes new scalar keys
- Created `validationPresets.ts` with 13-entry `VALIDATION_PRESETS` const mirroring the backend preset list, plus `buildPrefixPattern()` helper
- Created `ValidationRuleEditor.tsx`: collapsible disclosure per field row, controlled from `field.rule` prop — preset picker, custom regex input, prefix builder with live pattern display, vocabulary textarea with fuzzy toggle/distance input, and per-field corrector checkbox (disabled with tooltip when batch-level corrector is off)
- Mounted `ValidationRuleEditor` in `FieldManager.tsx` — each field row now has a collapsible rule editor below it; `handleSaveTemplate` includes `field_rules` in the mutation payload
- Added batch-level corrector toggle + cap input to ConfigureStep Card 2 (below `PromptTemplateEditor`)
- Updated `ConfigureStep.handleStartExtraction` to include `field_rules`, `corrector_enabled`, `corrector_cap` in `createBatch` payload
- Updated `TemplateSelector.handleSelectTemplate` to accept full `Template` object and hydrate `MetadataField.rule` from `template.field_rules` on template load

## Task Commits

1. **Task 1: Extend Zustand store with FieldRule + corrector state** - `3b00706` (feat)
2. **Task 2: Build ValidationRuleEditor + presets file, mount in FieldManager** - `ebcfd6a` (feat)
3. **Task 3: Wire ConfigureStep batch-level corrector + send rules in createBatch + template round-trip** - `bbc4369` (feat)

## Files Created/Modified

- `apps/frontend/src/features/configure/validationPresets.ts` — Created: 13 presets + buildPrefixPattern()
- `apps/frontend/src/features/configure/ValidationRuleEditor.tsx` — Created: full disclosure editor (~230 lines)
- `apps/frontend/src/store/wizardStore.ts` — Extended: FieldRule import/re-export, MetadataField.rule, correctorEnabled/correctorCap state + 5 new actions, partialize updated
- `apps/frontend/src/features/configure/FieldManager.tsx` — Extended: ValidationRuleEditor mounted per field row; handleSaveTemplate includes field_rules
- `apps/frontend/src/features/configure/ConfigureStep.tsx` — Extended: corrector state wired; corrector UI added to Card 2; createBatch payload includes field_rules/corrector_enabled/corrector_cap
- `apps/frontend/src/features/configure/TemplateSelector.tsx` — Refactored: handleSelectTemplate accepts full Template; hydrates field.rule from field_rules on load

## Decisions Made

- `ValidationRuleEditor` uses `isExpanded` state + `<button>` collapse header (same pattern as `PromptTemplateEditor`) rather than the HTML `<details>` element — keeps the visual style consistent with the existing Parchment UI
- `TemplateSelector.handleSelectTemplate` refactored from 4 individual params to accept the full `Template` object — cleaner and extensible, avoids growing the param list further
- Template `field_rules` saving is handled in `FieldManager.handleSaveTemplate` (the mutation caller), not in `SaveTemplateDialog` (name-only input) — no change to `SaveTemplateDialog.tsx` required
- `acceptCorrectorProposal` updates both `editedData[field]` (to the proposed value) and `validation[field].status` (to 'valid') atomically, preventing the corrected badge persisting after curator accepts

## Deviations from Plan

None — plan executed exactly as written. The plan mentioned editing `SaveTemplateDialog.tsx` but it is only a name-input UI component; the actual mutation with `field_rules` is already fired from `FieldManager.handleSaveTemplate`, which was updated in Task 2 as required.

## Issues Encountered

None — TypeScript `--noEmit` passed cleanly after each task with zero errors.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Configure step fully wired for validation: curators can attach rules to fields, enable corrector, set a cap, save/load templates with rules, and the `createBatch` payload carries all config to the backend
- 08-04 (Results step badges, filter chips, SummaryBanner counts, soft-block export) can proceed — it uses `acceptCorrectorProposal`/`rejectCorrectorProposal` actions from this plan

---
*Phase: 08-validation-rules-engine*
*Completed: 2026-05-18*
