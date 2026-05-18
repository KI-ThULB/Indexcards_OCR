---
phase: 08-validation-rules-engine
verified: 2026-05-18T00:00:00Z
status: passed
score: 19/19 must-haves verified
re_verification: false
---

# Phase 8: Validation Rules Engine — Verification Report

**Phase Goal:** Add per-field validation (regex + closed vocabulary + LLM corrector) to the OCR pipeline. Rules attach to field definitions, snapshot at batch creation, run inline during VLM extraction, are re-runnable on demand, and surface as per-cell badges with filter chips and soft-block export gating. LLM corrector is opt-in per batch with a hard call cap, fires only on rule failure, uses a cheap text-only model by default, and always proposes corrections (never silently overwrites). The data shape produced is ready for the Phase 9 Verify cockpit to consume without further changes.

**Verified:** 2026-05-18
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| #  | Truth | Status | Evidence |
|----|-------|--------|----------|
| 1  | FieldRule and ValidationOutcome shapes exist in shared schema and codegen output | VERIFIED | `template.schema.json` line 5, `batch.schema.json` line 20, `generated/ts/index.ts` lines 3–16 |
| 2  | Pydantic schemas.py exposes FieldRule, ValidationOutcome, extended BatchCreate/BatchConfig/ExtractionResult/Template | VERIFIED | `schemas.py`: `class FieldRule` at line 8, `class ValidationOutcome` at line 15, all five model classes extended with null/false/100 defaults |
| 3  | Frontend BatchCreate type accepts field_rules, corrector_enabled, corrector_cap | VERIFIED | `batchesApi.ts` lines 27–29 |
| 4  | Existing batches without field_rules deserialize without error (backward compatibility) | VERIFIED | All new Pydantic fields default to None/False/100; `ResultsStep.tsx` hydrates `r.validation ?? null` |
| 5  | Validation rules execute inline during VLM extraction and emit per-field ValidationOutcome into ExtractionResult | VERIFIED | `ocr_engine.py` lines 318–343: `run_validation` called after VLM, `"validation": validation_outcomes or None` in result dict |
| 6  | Rules snapshotted into batch config.json at creation, read back at run-time | VERIFIED | `batch_manager.py` lines 62–64 write `field_rules/corrector_enabled/corrector_cap`; `batches.py` lines 50–52 read them back |
| 7  | LLM corrector fires only on rule failure, only when batch corrector_enabled=True, never exceeds cap | VERIFIED | `corrector.py`: thread-safe cap check at lines 41–59; `runner.py`: `should_correct = corrector_enabled and rule.get("corrector_enabled", False)` guards the call |
| 8  | POST /revalidate re-runs validation without re-extracting | VERIFIED | `batches.py` line 198: `@router.post("/{batch_name}/revalidate")`; reads config.json, loops checkpoint.json, writes updated validation map |
| 9  | Curator can attach a rule (regex preset / custom regex / vocabulary) to any field | VERIFIED | `ValidationRuleEditor.tsx` (308 lines), mounted in `FieldManager.tsx` line 120 via `ValidationRuleEditor` component |
| 10 | Curator can enable LLM corrector for the batch and set a per-batch call cap | VERIFIED | `ConfigureStep.tsx` lines 140–155: corrector checkbox + cap number input; reads/writes `correctorEnabled`/`correctorCap` from store |
| 11 | Field rules and corrector state persist in Zustand and survive page refresh | VERIFIED | `wizardStore.ts` lines 288–289: `correctorEnabled` and `correctorCap` in `partialize`; field `rule` rides on existing persisted `fields` array |
| 12 | Saving a template captures field_rules; loading restores them | VERIFIED | `FieldManager.tsx` `handleSaveTemplate` sends `field_rules`; `TemplateSelector.tsx` line 30: `rule: template.field_rules?.[label] ?? null` on load |
| 13 | createBatch payload includes field_rules / corrector_enabled / corrector_cap when set | VERIFIED | `ConfigureStep.tsx` lines 60–62: `field_rules`, `corrector_enabled`, `corrector_cap` in `createBatch` call |
| 14 | Per-cell ValidationBadge renders correct icon/color for each status with hover tooltip | VERIFIED | `ValidationBadge.tsx` (108 lines): CheckCircle/XCircle/Wand2 icons, hover tooltip with rule detail and Accept/Reject for corrected status |
| 15 | Accept/Reject corrector proposal updates editedData and flips validation status | VERIFIED | `ValidationBadge.tsx` lines 62 and 72 call `acceptCorrectorProposal`/`rejectCorrectorProposal`; store actions update both `editedData` and `validation[field].status` atomically |
| 16 | Filter chips above table filter rows by validation status | VERIFIED | `ValidationFilterChips.tsx` (58 lines); `ResultsTable.tsx` `filteredResults` useMemo at lines 131–141 |
| 17 | SummaryBanner shows aggregate invalid + corrected proposal counts | VERIFIED | `SummaryBanner.tsx` lines 76–85: amber Invalid and blue Proposals columns, hidden when zero |
| 18 | Export soft-block: sonner warning toast when invalid rows exist | VERIFIED | `useResultsExport.ts`: `checkValidationGate` helper wraps all 8 download functions (CSV/JSON/LIDO/EAD/DarwinCore/DublinCore/MARCXML/METSMOD) at lines 57–586 |
| 19 | ResultRow.validation shape is the Phase 9 contract — unchanged consumption from Verify cockpit | VERIFIED | `wizardStore.ts` `ResultRow.validation?: Record<string, ValidationOutcome> | null`; hydrated via `r.validation ?? null` in `ResultsStep.tsx` — no schema changes required for Phase 9 |

**Score:** 19/19 truths verified

---

### Required Artifacts

| Artifact | Status | Details |
|----------|--------|---------|
| `packages/shared-types/schemas/template.schema.json` | VERIFIED | FieldRule definition at line 5; field_rules on Template/TemplateCreate/TemplateUpdate |
| `packages/shared-types/schemas/batch.schema.json` | VERIFIED | FieldRule inlined at line 5; ValidationOutcome at line 20; field_rules/corrector_enabled/corrector_cap on BatchConfig/BatchCreate; validation on ExtractionResult |
| `packages/shared-types/generated/ts/index.ts` | VERIFIED | FieldRule, ValidationOutcome, field_rules, corrector_enabled, corrector_cap, validation interfaces all present |
| `apps/backend/app/models/schemas.py` | VERIFIED | class FieldRule (line 8), class ValidationOutcome (line 15); BatchConfig/BatchCreate/ExtractionResult/Template/TemplateCreate/TemplateUpdate all extended with backward-compatible defaults |
| `apps/frontend/src/api/batchesApi.ts` | VERIFIED | FieldRule (line 6), ValidationOutcome (line 14), BatchCreate extended (lines 27–29) |
| `apps/backend/app/services/validation/runner.py` | VERIFIED | 65 lines (min 60); run_validation orchestrator with per-field regex -> vocab -> corrector pipeline |
| `apps/backend/app/services/validation/regex_rules.py` | VERIFIED | 17 lines (min 15); lru_cache compiled matcher; check_regex function |
| `apps/backend/app/services/validation/vocab_rules.py` | VERIFIED | 32 lines (min 30); normalize_value + matches_vocabulary with opt-in fuzzy rapidfuzz |
| `apps/backend/app/services/validation/corrector.py` | VERIFIED | 161 lines (min 50); thread-safe cap via lock; all exceptions caught; never raises |
| `apps/backend/app/services/validation/presets.py` | VERIFIED | VALIDATION_PRESETS at line 13; 12 preset entries |
| `apps/backend/app/api/api_v1/endpoints/batches.py` | VERIFIED | revalidate at line 198–251; reads config.json, re-runs validation on checkpoint.json |
| `apps/frontend/src/features/configure/validationPresets.ts` | VERIFIED | 29 lines; VALIDATION_PRESETS const with 13 entries + buildPrefixPattern() |
| `apps/frontend/src/features/configure/ValidationRuleEditor.tsx` | VERIFIED | 308 lines (min 100); preset picker, custom regex, prefix builder, vocabulary textarea, fuzzy toggle, per-field corrector checkbox |
| `apps/frontend/src/features/configure/FieldManager.tsx` | VERIFIED | ValidationRuleEditor imported (line 8) and mounted per field row (line 120) |
| `apps/frontend/src/features/configure/ConfigureStep.tsx` | VERIFIED | correctorEnabled at line 140; correctorCap at line 153; field_rules in createBatch at line 60 |
| `apps/frontend/src/store/wizardStore.ts` | VERIFIED | correctorEnabled/correctorCap state + 5 actions (updateFieldRule, setCorrectorEnabled, setCorrectorCap, acceptCorrectorProposal, rejectCorrectorProposal); partialize includes new keys |
| `apps/frontend/src/features/results/ValidationBadge.tsx` | VERIFIED | 108 lines (min 60); per-cell badge with icons, hover tooltip, Accept/Reject buttons |
| `apps/frontend/src/features/results/ValidationFilterChips.tsx` | VERIFIED | 58 lines (min 40); four Parchment chip buttons with counts |
| `apps/frontend/src/features/results/ResultsTable.tsx` | VERIFIED | ValidationBadge imported (line 15) and rendered inside each extraction dd (line 289) |
| `apps/frontend/src/features/results/ResultsStep.tsx` | VERIFIED | validation hydrated (line 47); ValidationFilterChips rendered (line 207); invalidCount/correctedCount passed to SummaryBanner |
| `apps/frontend/src/features/results/SummaryBanner.tsx` | VERIFIED | invalidCount/correctedCount optional props (lines 19–20); stat columns rendered conditionally |
| `apps/frontend/src/features/results/useResultsExport.ts` | VERIFIED | checkValidationGate at line 38; all 8 download functions wrapped at lines 57, 97, 134, 232, 290, 350, 421, 586 |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `ocr_engine.py::_process_card_sync` | `validation/runner.py::run_validation` | Call after VLM, before result return | WIRED | Line 319: `from app.services.validation.runner import run_validation`; line 343: `"validation": validation_outcomes or None` in result dict |
| `batch_manager.py::create_batch` | `config.json` | JSON snapshot of field_rules/corrector_enabled/corrector_cap | WIRED | Lines 62–64 write all three keys into `config_data` |
| `batches.py::run_ocr_task` | `ocr_engine.process_batch` | field_rules/corrector_enabled/corrector_cap threaded through call chain | WIRED | Lines 50–52 read from config; lines 74–76 pass to process_batch |
| `template_service.py` | Template field_rules | create_template/update_template persist field_rules | WIRED | Line 48: `field_rules=template_in.field_rules`; lines 64–65: `is not None` guard on update |
| `ConfigureStep.tsx::handleStartExtraction` | `batchesApi.ts::createBatch` | BatchCreate payload includes field_rules + corrector_enabled + corrector_cap | WIRED | Lines 60–62 in ConfigureStep.tsx |
| `FieldManager.tsx` | `wizardStore.ts` | updateFieldRule(fieldId, rule) on ValidationRuleEditor onChange | WIRED | Line 123: `onChange={(rule) => updateFieldRule(field.id, rule)}` |
| `TemplateSelector.tsx` | `wizardStore.ts` | loadTemplate hydrates fields including rule property | WIRED | Line 30: `rule: template.field_rules?.[label] ?? null` in field map |
| `ResultsTable.tsx` | `ValidationBadge.tsx` | `<ValidationBadge outcome={r.validation?.[field]} .../>` in each dd | WIRED | Lines 15 (import) and 289 (render) in ResultsTable.tsx |
| `ValidationBadge.tsx` | `wizardStore.ts` | Accept/Reject call acceptCorrectorProposal/rejectCorrectorProposal | WIRED | Lines 13, 62, 72 in ValidationBadge.tsx |
| `useResultsExport.ts` | sonner toast | soft-block pattern wrapping all 8 download functions | WIRED | Line 48: `toast.warning(...)` with action+cancel; 8 download functions wrapped |
| `ResultsStep.tsx` | API hydration | `r.validation ?? null` on every result row | WIRED | Line 47 in ResultsStep.tsx |

---

### Requirements Coverage

| Requirement | Source Plans | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| FR2 — Metadata Field Configuration | 08-01, 08-02, 08-03 | Users can define fields to be extracted; field names update the VLM prompt | SATISFIED | FieldRule attached to field definitions; ValidationRuleEditor in FieldManager; template round-trip |
| FR3 — OCR Processing & Progress Tracking | 08-02 | Backend processes images using VLM; resilient error handling | SATISFIED | Validation runs inline inside `_process_card_sync`; entire validation block wrapped in try/except — never blocks extraction |
| FR4 — Results Visualization & Export | 08-01, 08-02, 08-04 | Summary of results; CSV download | SATISFIED | ValidationBadge per cell; SummaryBanner counts; filter chips; export soft-block gate across all 8 formats |

No orphaned requirements found — all phase-8 requirement IDs (FR2, FR3, FR4) appear in plan frontmatter and are covered by implementation evidence.

---

### Anti-Patterns Found

No blockers or warnings found. The two `return null` occurrences in `ValidationBadge.tsx` (lines 16 and 83) are intentional: the component correctly renders nothing for skipped/absent outcomes. The `placeholder` attributes in `ValidationRuleEditor.tsx` are input hints for the editor UI — not implementation stubs.

---

### Human Verification Required

#### 1. ValidationRuleEditor UX in browser

**Test:** Open Configure step, add a field, expand the rule editor. Select each preset in sequence: Year, Custom Regex (type a pattern), Closed Vocabulary (enter terms, enable fuzzy), Prefix Pattern, No rule.
**Expected:** Each preset shows the correct control set; selecting "No rule" clears the rule; changing presets resets controls cleanly.
**Why human:** Visual rendering and control interaction cannot be verified via grep.

#### 2. Accept/Reject corrector proposal interaction

**Test:** Run a batch with corrector_enabled=true, a field with a vocabulary rule that will fail, and a real OpenRouter API key. In the Results table, hover the amber Wand badge.
**Expected:** Tooltip stays open when cursor moves to it (not CSS-only hover); Accept changes cell value and turns badge green; Reject leaves cell value unchanged and turns badge red.
**Why human:** Mouse-enter/leave interactive tooltip behavior and state mutation visual feedback require a browser.

#### 3. Sonner export gate in browser

**Test:** Open a batch with at least one row where a field has `status: "invalid"` in validation. Click CSV export.
**Expected:** Sonner toast appears with "N rows have validation issues", "Export anyway" and "Cancel" action buttons. Cancel dismisses without download; "Export anyway" triggers download.
**Why human:** Sonner toast rendering and button interaction require a browser.

#### 4. Filter chips row-count accuracy

**Test:** With a batch having mixed valid/invalid/corrected outcomes, click each filter chip in sequence.
**Expected:** Table row count matches the chip count label; "All" restores all rows.
**Why human:** Row counts depend on live state and visual table rendering.

---

## Gaps Summary

No gaps. All 19 observable truths verified, all 22 artifacts pass all three levels (exists, substantive, wired), all 11 key links wired. Requirements FR2, FR3, FR4 satisfied. No blocker anti-patterns. Phase 8 goal fully achieved.

---

_Verified: 2026-05-18_
_Verifier: Claude (gsd-verifier)_
