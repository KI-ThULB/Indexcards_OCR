# Phase 9: Verification Cockpit - Context

**Gathered:** 2026-05-18
**Status:** Ready for planning

<domain>
## Phase Boundary

A focused review/correction workspace as a new wizard step. Curator works one card at a time with a deep-zoom image on one side and the extracted fields on the other, marking each field verified or corrected, using keyboard navigation. Consumes Phase 8's `validation` shape (per-cell `ValidationOutcome`) and produces the final verified data that downstream stages (Phase 10 cleaning, Phase 11 reconciliation, and exports) will trust.

**In scope:** new optional wizard step, side-by-side cockpit, inline editing in cockpit, per-field verified status, keyboard navigation, filmstrip card nav, multi-entry tabs, persistence via the existing edit endpoint.

**Out of scope:** ROI overlay (deferred — current OCR engine does not produce bounding boxes), bulk batch operations, mobile-first layout.

</domain>

<decisions>
## Implementation Decisions

### Workflow placement & scope
- Verify is an **optional step after Results**, not a mandatory step. Entry point is a "Verify cards" affordance from Results (toolbar button or sidebar step item). Curators with quick batches skip it; thorough cataloging uses it.
- Default card scope on entry: **only cards with validation issues** (at least one field with `status` in `invalid` / `corrected`). Filter chips at the top of the cockpit let the curator switch to "All cards" or other validation-status filters.
- Inside the cockpit, fields are **inline editable** (same `EditableCell` textarea pattern as Results). Read image → fix text → mark verified → next field is one motion.
- Corrector proposals from Phase 8 are shown **inline with Accept/Reject buttons**, mirroring the Phase 8 `ValidationBadge` behavior in Results. Same wiring (`acceptCorrectorProposal` / `rejectCorrectorProposal` Zustand actions). Never auto-applied — preserves the Phase 8 "always proposes, never silently overwrites" policy.

### Cockpit layout & zoom mechanics
- **50/50 split** between image (left) and fields (right), with a **resizable vertical drag handle**. Split position persisted in Zustand so each curator's preference sticks across sessions.
- **Deep-zoom = wheel-zoom + drag-pan + double-click-reset** applied via CSS transform on the original full-res JPEG. No new dependency, no tile generation. A5 cards at typical scan resolution are well within browser-decode comfort.
- **Card navigation = thin filmstrip along the bottom** of the cockpit. Small thumbnails (~40–60px), current card highlighted, scrollable horizontally, clickable to jump. Filter chips (only-invalid / corrected / all) sit above the filmstrip.
- **Multi-entry cards** (Findmittel-style, from Phase 6): image stays fixed, **field pane gets tabs** — one per entry ("Entry 1", "Entry 2", …). Each entry verified independently. Filmstrip shows the card once with an entry-count badge.

### Status model & key shortcuts
- **Add `verified` as a fourth value on the existing Phase 8 `ValidationOutcome.status`** field. Values become: `valid` | `invalid` | `corrected` | `verified`. Single source of truth across Results, Verify, and exports.
- **Edit auto-flips status to `verified`** on save. The act of correcting and committing the value is itself a verification — no separate keystroke required. Empty/discarded edits do not change status.
- **Keyboard shortcuts (mixed convention):**
  - `Tab` / `Shift+Tab` — next/previous field (standard form UX)
  - `J` / `K` — next/previous card (Vim/Gmail/Reader pattern; safe inside text inputs because plain letters require focus to be outside an active edit)
  - `V` — mark current field as verified
  - `Enter` — accept the active corrector proposal (when present)
  - `Esc` — exit the active edit (does NOT leave the cockpit)
- **Persistence:** reuse the **existing edit endpoint** for results (PATCH/POST whichever Results already uses), extended to carry the `validation[field].status` update alongside the value. One endpoint, one persistence path, no new backend wiring. Checkpoint.json shape stays the single source of truth that exports and Phase 10/11 consume.

### Claude's Discretion
- Exact drag-handle visual + minimum pane widths
- Filmstrip thumbnail dimensions, hover affordances, and scroll behavior
- Zoom min/max bounds, zoom-toward-cursor curve, double-click reset target
- Edit-save debounce timing
- Whether to show a "verified N/M" progress indicator and where
- What happens on cockpit exit (auto-save on leave is assumed; final UX details up to Claude)
- How filter chips on the filmstrip persist between sessions
- Rejected-proposal status — likely stays `invalid` until manual edit; Claude can settle this during planning
- Whether plain-Enter inside a textarea inserts a newline (probably yes, matching Phase 6 EditableCell) and how that coexists with "Enter accepts proposal" (only when no edit is active)

</decisions>

<specifics>
## Specific Ideas

- The cockpit should feel like an **IDE diff view** or a **photo-cataloging tool**: dense, keyboard-driven, image on one side, structured data on the other, fast card-to-card flow.
- The filmstrip is the **Lightroom/Bridge** pattern — the user explicitly chose it over a side panel for the "at a glance" preview value.
- The "verified" status is a **human-confirmed signal** distinct from auto-passed `valid`. Exports and later phases can treat them differently (e.g., reconciliation in Phase 11 might trust `verified` more than `valid`).
- Multi-entry tabs over stacked blocks: the user wants the image-while-typing benefit preserved for each entry independently.
- The corrector inline UX intentionally mirrors Results so curators don't learn two patterns.

</specifics>

<deferred>
## Deferred Ideas

- **ROI overlay** — Bounding-box overlay on the image showing which region produced each field's value. Requires either swapping to a grounding-capable VLM (Qwen3-VL-Plus, Gemini, GPT-4o with bbox output) or a separate detection pass. Not shipped in Phase 9; the cockpit ships without the toggle. Candidate for its own phase once a VLM-with-grounding is chosen.
- **Bulk verification actions** — "verify all remaining clean fields", "mark card complete in one keystroke", "verify entire batch". Possible follow-up after the per-field flow has been validated in real curator use.
- **Mobile / narrow-screen layout** — the 50/50 split is desktop-only by design; mobile fallback (likely stacked vertical or a single-pane toggle) belongs in a separate accessibility/responsive phase.
- **Verification audit log** — who verified what when. Useful for multi-curator institutions but adds backend storage; defer until there's evidence of multi-curator use.

</deferred>

---

*Phase: 09-verification-cockpit*
*Context gathered: 2026-05-18*
