# Phase 8: Validation Rules Engine - Context

**Gathered:** 2026-05-13
**Status:** Ready for planning

<domain>
## Phase Boundary

Per-field validation rules (regex / closed vocabulary / LLM corrector) applied after VLM extraction. Status surfaces in the existing Results table; the data shape must also be ready for the Verify view (Phase 9). The Configure step gains a rule editor on each field. The Verify view itself, OpenRefine-style bulk cleaning, and authority reconciliation are out of scope (Phases 9, 10, 11).

</domain>

<decisions>
## Implementation Decisions

### Rule storage & lifecycle
- Rules attached **directly to the field definition** in templates and batches — no separate "validation profile" abstraction. One rule (regex + vocabulary + corrector config) per field, optional.
- Rules **execute inline during VLM extraction** (in `OcrEngine.process_image` / `process_batch`) AND must be **re-runnable on demand** without re-extracting. New endpoint(s) needed to re-run validation against an existing batch's results.
- Rules are **snapshotted at batch creation time**, same pattern as the existing `prompt_template`. Old batches retain their original rule set; current template edits do not retroactively re-validate them.
- Validation outcome is stored **inline alongside the value** in the existing result row, e.g. `result.validation[field] = { status, rule_failed?, original_value?, rationale?, corrector_proposal? }`. Single source of truth — no separate validation report file. Frontend derives badges/filter state from this.

### LLM corrector — when, what, how
- Corrector fires **only when regex or vocabulary rule fails** (not always, not manual-only). Cheap fallback for the hard cases.
- Default model is a **cheap text-only model** (e.g. Claude Haiku via OpenRouter, or a comparable small model) — ~10x cheaper than Qwen-VL for "is this string close to a valid form?". An **opt-in image fallback** sends the image to the configured extraction VLM when a rule's correction needs visual context (handwriting reread).
- Corrections are **always proposed, never silently auto-applied**. The cell shows original value + proposed value + rationale; one-click accept/reject by the curator. Matches museum-curatorial transparency norms.
- Cost control: **opt-in per batch + hard cap**. Configure step has an "Enable LLM correction for this batch" toggle (off by default); when on, a per-batch correction-call cap (default ~100, configurable) prevents runaway spend.

### Rule library: regex presets + vocab matching
- Configure-step rule editor offers a **curated preset library + custom-regex escape hatch**. Presets are the entry point for non-technical curators; custom regex is available in an "advanced" disclosure.
- **v1 preset list:**
  - Year (`YYYY`) and year range (`YYYY–YYYY`)
  - ISO date (`YYYY-MM-DD`) and German date (`DD.MM.YYYY`)
  - Authority ID patterns: GND, RKD, AAT, VIAF
  - Configurable **prefix pattern** (user supplies prefix like `KMB-`, preset generates the regex)
  - Required / non-empty
- Closed-vocabulary matching: **case-insensitive exact by default**; **fuzzy (Levenshtein) is opt-in per rule** with a configurable distance (default 1).
- Vocabulary normalization (deterministic, not fuzzy): **trim whitespace + NFC + case-fold + diacritic-fold**. So `"Goethe"`, `" goethe "`, `"GÖTHE"`, `"GOETHE"` all match the canonical entry. Fuzzy matching is a separate opt-in layer on top.

### Status surfacing in Results
- **Per-cell inline badge** next to each value in the existing dl/dd extraction column. No separate validation column for v1; row-summary chips can be added later if needed.
- **Filter chips** above the Results table: `All` / `Only invalid` / `Only auto-corrected (proposed)` / `Only verified-OK`. One-click filtering of the table.
- Export gate: **soft-block with confirmation dialog**. CSV/JSON/XML export still works; a dialog appears if any row has open invalid status: "N rows have validation issues. Export anyway?". No hard-block — sometimes work-in-progress must ship.
- Badge style: **color + lucide-react icon + tooltip**. Tooltip on hover shows which rule failed, the original VLM output, and (for corrections) the proposed value. Matches the existing Parchment theme and the existing icon usage in ResultsTable.
- The summary banner (existing `SummaryBanner.tsx`) should also surface aggregate validation counts (e.g. "12 invalid · 4 auto-corrected proposals pending"). Planner to wire this in.

### Claude's Discretion
- Configure-step rule editor UX (where exactly the disclosure sits in `FieldManager`, animation, save-with-template ergonomics) — defer to existing FieldManager pattern.
- Exact corrector prompt construction (system prompt, JSON output schema, retry/fallback if corrector errors).
- Backend module boundaries within `apps/backend/app/services/validation/` (regex/vocab/corrector adapters, runner orchestration).
- Whether the per-batch cap is a soft warning at threshold + hard stop at cap, or a single hard stop.
- Fuzzy matching algorithm choice (Levenshtein vs damerau-levenshtein vs metaphone) — pick whatever standard library covers it.
- Choice of cheap default corrector model — pick best price/quality available via the existing provider abstraction (`_resolve_provider`).

</decisions>

<specifics>
## Specific Ideas

- The existing pattern of `prompt_template` (snapshot at batch, optional, configurable per template) is the model for rule storage. Mimic that pattern faithfully.
- Existing JSON Schema codegen pipeline (`packages/shared-types`) is the source of truth — schema additions for the rule shape go there first, then regenerate Pydantic + TypeScript types.
- Existing `_resolve_provider` pattern in `OcrEngine` should be reused for the corrector's call-time provider override — no global mutation, no new provider abstraction.
- LIDO and MARCXML are tighter on data quality than CSV in real curatorial life — leaving "configurable per export format" on the table for later, but v1 ships uniform soft-block.
- Filter chips should match existing Parchment-theme component styling (rounded, sepia border, hover states already used by other UI elements).
- Curators have explicitly mentioned needing transparency: machine corrections must always be visible and reversible, never silent.

</specifics>

<deferred>
## Deferred Ideas

- **Configurable per-export-format gate** (LIDO/MARCXML hard-block, CSV soft-block) — not v1; revisit after observing real export friction.
- **Save user's custom regex as a personal preset** — nice-to-have; v1 has the curated library only.
- **Bulk-apply rule across fields of the same type** ("set Year preset on all year-typed fields") — usability win, not blocking; future Configure-step polish phase.
- **Row-summary validation chip** on each Results row in addition to per-cell badges — depends on whether per-cell badges feel insufficient in practice.
- **Mixed apply mode** (auto-apply for vocab snaps, propose for free-form regex) — possibly ideal long-term, complicates v1 logic. Revisit if curators ask.
- **Always-on corrector** (vs the chosen opt-in default) — if cost stops being a concern, flip the default later.
- **Internationalization of error text** (de-DE vs en-US for tooltips/dialogs) — current app is German-leaning but mixed; out of scope for this phase.
- **Multi-pattern OR rules** ("matches GND ID OR Wikidata Q-ID") — useful when a field accepts multiple authority kinds; deferred to Phase 11 (reconciliation).
- **Configure-step rule editor: separate Validation tab vs inline disclosure** — planner's discretion based on existing FieldManager layout, but the "ideal" multi-rule-per-field editor is deferred.

</deferred>

---

*Phase: 08-validation-rules-engine*
*Context gathered: 2026-05-13*
