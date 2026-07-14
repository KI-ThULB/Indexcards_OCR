# Phase 09: Verification Cockpit — Research

**Researched:** 2026-05-18
**Domain:** Frontend-heavy — new wizard step, image zoom/pan, keyboard shortcuts, Zustand state extension, backend PATCH endpoint
**Confidence:** HIGH (codebase confirmed, no external library additions required)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Workflow placement & scope**
- Verify is an **optional step after Results**, not a mandatory step. Entry point is a "Verify cards" affordance from Results (toolbar button or sidebar step item). Curators with quick batches skip it; thorough cataloging uses it.
- Default card scope on entry: **only cards with validation issues** (at least one field with `status` in `invalid` / `corrected`). Filter chips at the top of the cockpit let the curator switch to "All cards" or other validation-status filters.
- Inside the cockpit, fields are **inline editable** (same `EditableCell` textarea pattern as Results). Read image → fix text → mark verified → next field is one motion.
- Corrector proposals from Phase 8 are shown **inline with Accept/Reject buttons**, mirroring the Phase 8 `ValidationBadge` behavior in Results. Same wiring (`acceptCorrectorProposal` / `rejectCorrectorProposal` Zustand actions). Never auto-applied — preserves the Phase 8 "always proposes, never silently overwrites" policy.

**Cockpit layout & zoom mechanics**
- **50/50 split** between image (left) and fields (right), with a **resizable vertical drag handle**. Split position persisted in Zustand so each curator's preference sticks across sessions.
- **Deep-zoom = wheel-zoom + drag-pan + double-click-reset** applied via CSS transform on the original full-res JPEG. No new dependency, no tile generation. A5 cards at typical scan resolution are well within browser-decode comfort.
- **Card navigation = thin filmstrip along the bottom** of the cockpit. Small thumbnails (~40–60px), current card highlighted, scrollable horizontally, clickable to jump. Filter chips (only-invalid / corrected / all) sit above the filmstrip.
- **Multi-entry cards** (Findmittel-style, from Phase 6): image stays fixed, **field pane gets tabs** — one per entry ("Entry 1", "Entry 2", …). Each entry verified independently. Filmstrip shows the card once with an entry-count badge.

**Status model & key shortcuts**
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

### Deferred Ideas (OUT OF SCOPE)
- **ROI overlay** — Bounding-box overlay on the image showing which region produced each field's value. Requires either swapping to a grounding-capable VLM (Qwen3-VL-Plus, Gemini, GPT-4o with bbox output) or a separate detection pass. Not shipped in Phase 9; the cockpit ships without the toggle. Candidate for its own phase once a VLM-with-grounding is chosen.
- **Bulk verification actions** — "verify all remaining clean fields", "mark card complete in one keystroke", "verify entire batch". Possible follow-up after the per-field flow has been validated in real curator use.
- **Mobile / narrow-screen layout** — the 50/50 split is desktop-only by design; mobile fallback (likely stacked vertical or a single-pane toggle) belongs in a separate accessibility/responsive phase.
- **Verification audit log** — who verified what when. Useful for multi-curator institutions but adds backend storage; defer until there's evidence of multi-curator use.
</user_constraints>

---

## Summary

Phase 9 is a pure frontend phase with one small backend extension. The entire cockpit lives in a new `features/verify/` directory added to the existing React app. It introduces a new `WizardStep` value (`'verify'`), a new `AppView` routing variant, and extends the existing Zustand store with cockpit-specific state. No new npm dependencies are needed: the zoom/pan pattern mirrors the existing `ImagePreview` canvas-magnifier approach, the editable field pattern reuses `EditableCell` verbatim, and the `ValidationBadge` Accept/Reject wiring reuses the Phase 8 Zustand actions unchanged.

The only backend touch is a new `PATCH /api/v1/batches/{batch_name}/results/{filename}` endpoint that writes a single row's `editedData` and `validation` overrides back to `checkpoint.json`. This replaces the current "all edits live only in Zustand" pattern and makes verification durable. The endpoint shape is simple: `{ field, value, validation_status }` or a bulk `{ edits: {...}, validation: {...} }`. Checkpoint.json already owns the authoritative shape; the PATCH just merges into it.

The deepest implementation work is the drag-handle resize and the keyboard event guard. Both are standard DOM patterns with no library requirement. The `j`/`k` guard (do not fire while a text input has focus) is one `document.activeElement instanceof HTMLTextAreaElement` check. The drag handle is a `mousedown`/`mousemove`/`mouseup` pattern with `user-select: none` during drag.

**Primary recommendation:** Build the cockpit as a new `'verify'` WizardStep rendered by `App.tsx`, use CSS `transform: scale + translate` for zoom/pan (same approach as existing magnifier but inverted — transform the image itself rather than a lens overlay), and extend `checkpoint.json` PATCH endpoint as the sole persistence mechanism.

---

## Standard Stack

### Core (no new additions)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| React 19 | `^19.2.0` | Component tree | Already installed |
| Zustand 5 | `^5.0.11` | State — cockpit pane split, active card index, filter chip | Already installed |
| Tailwind 3.4 | `3.4` | Layout — flex/grid, gap, overflow | Already installed |
| lucide-react | `^0.575.0` | Icons for toolbar (CheckCircle2, ArrowLeft, etc.) | Already installed |
| axios | `^1.13.5` | PATCH /results/{filename} call | Already installed |
| @tanstack/react-query | `^5.90.21` | Mutation for PATCH call | Already installed |

### No New Dependencies Required
The zoom/pan implementation uses CSS `transform` + DOM event listeners — identical approach to the existing `ImagePreview` magnifier (`ImagePreview.tsx` lines 1–134), no library needed. The filmstrip is a horizontally-scrollable `<div>` with `overflow-x-auto`. The drag handle is pure DOM.

---

## Architecture Patterns

### Recommended Project Structure
```
apps/frontend/src/features/verify/
├── VerifyStep.tsx           # Top-level step container, keyboard listener, card carousel
├── CockpitLayout.tsx        # Resizable 50/50 split container with drag handle
├── ImagePane.tsx            # Full-res JPEG with wheel-zoom + drag-pan + dbl-click-reset
├── FieldsPane.tsx           # Scrollable field list with EditableCell + CockpitBadge per field
├── CockpitBadge.tsx         # ValidationBadge variant with "verified" state support
├── Filmstrip.tsx            # Bottom horizontal strip — card thumbnails + filter chips
└── useVerifyKeyboard.ts     # Keyboard shortcut hook (j/k/v/Enter/Esc guard logic)
```

### Pattern 1: New WizardStep Value
**What:** Add `'verify'` to `WizardStep` union in `wizardStore.ts`.
**When to use:** Cockpit is a wizard step, not a new AppView.

Current union:
```typescript
// wizardStore.ts line 6
export type WizardStep = 'upload' | 'configure' | 'processing' | 'results';
```

Becomes:
```typescript
export type WizardStep = 'upload' | 'configure' | 'processing' | 'results' | 'verify';
```

App.tsx switch adds:
```typescript
case 'verify':
  return <VerifyStep />;
```

### Pattern 2: Sidebar Step Registration
**What:** Add `'verify'` to the `STEPS` array in `Sidebar.tsx`.
**Critical guard:** The existing `handleStepClick` guard at line 40–55 must be extended to allow clicking `'verify'` only when `batchId` is set **and** at least one result has validation data (or always allow when `batchId` is set — simpler). The `isClickable` logic at line 105–107 derives from `getStepStatus`, which uses `stepOrder`. Append `'verify'` to `stepOrder`.

Current stepOrder in Sidebar:
```typescript
// Sidebar.tsx line 31
const stepOrder: WizardStep[] = ['upload', 'configure', 'processing', 'results'];
```

Becomes:
```typescript
const stepOrder: WizardStep[] = ['upload', 'configure', 'processing', 'results', 'verify'];
```

The `handleStepClick` for `'verify'` should behave like `'results'`: clickable only when `batchId` is set.

### Pattern 3: Zustand State Extension — Cockpit
**What:** Add cockpit-specific state to `wizardStore.ts`. Most cockpit UI state is transient (current card index, zoom level) and should NOT be in the `partialize` list. Only `cockpitSplitPercent` (curator's preferred pane width) should persist.

```typescript
// New fields in WizardState:
cockpitSplitPercent: number;       // 50 default — persisted
setCockpitSplitPercent: (v: number) => void;

// In initialState:
cockpitSplitPercent: 50,

// In partialize list (add):
cockpitSplitPercent: state.cockpitSplitPercent,
```

Transient cockpit state (active card index, zoom transform, filter chip selection) belongs in local component state, not Zustand — no persistence, no re-render blast to unrelated components.

**CRITICAL:** The existing `partialize` block (lines 276–291 of `wizardStore.ts`) must be updated when adding `cockpitSplitPercent`. Forgetting this causes the preference to evaporate on page reload.

### Pattern 4: Wheel-Zoom + Drag-Pan on Full-Res Image
**What:** CSS `transform: scale(z) translate(x, y)` applied to the `<img>` element via `useRef`. Wheel event adjusts scale. Mouse-drag while holding left button adjusts translate. Double-click resets.

Reference pattern from `ImagePreview.tsx` (existing): uses `requestAnimationFrame` + `transform: translate3d` for zero-layout-cost updates. Phase 9 inverts the pattern — instead of a fixed-position lens over a static image, the image itself transforms.

```typescript
// ImagePane.tsx skeleton
const scale = useRef(1);
const tx = useRef(0);
const ty = useRef(0);
const imgRef = useRef<HTMLImageElement>(null);

const applyTransform = () => {
  if (imgRef.current) {
    imgRef.current.style.transform = `scale(${scale.current}) translate(${tx.current}px, ${ty.current}px)`;
  }
};

// Wheel: adjust scale clamped to [0.5, 8], zoom toward cursor
const handleWheel = (e: WheelEvent) => {
  e.preventDefault();
  const delta = e.deltaY > 0 ? 0.9 : 1.1;
  scale.current = Math.max(0.5, Math.min(8, scale.current * delta));
  applyTransform();
};

// Drag-pan: track mousedown/mousemove/mouseup on container
// Double-click: scale.current = 1; tx.current = 0; ty.current = 0;
```

Attach `wheel` listener with `{ passive: false }` to prevent default scroll (required for zoom-within-pane).

### Pattern 5: `validated` Fourth Status — Schema + Codegen Change
**What:** `ValidationOutcome.status` gains a fourth enum value `'verified'`. This flows through:

1. `packages/shared-types/schemas/batch.schema.json` — change enum from `["valid", "invalid", "corrected", "skipped"]` to `["valid", "invalid", "corrected", "skipped", "verified"]`
2. Run `turbo generate` to regenerate `generated/ts/index.ts`
3. `apps/backend/app/models/schemas.py` — `ValidationOutcome.status` is currently `str` (no enum constraint), so **no Pydantic change needed**. The backend already accepts any string via `status: str`.
4. `apps/frontend/src/api/batchesApi.ts` — **manual update required** (local TS type copy; does not use codegen). Change `status: 'valid' | 'invalid' | 'corrected' | 'skipped'` to include `'verified'`.
5. `apps/frontend/src/store/wizardStore.ts` — `ValidationOutcome` re-exported from `batchesApi.ts`. Update follows automatically once batchesApi.ts is fixed.
6. `ValidationBadge.tsx` — add `'verified'` case (show a distinct icon, e.g. `CheckCircle2` in emerald to distinguish from `valid`'s `CheckCircle`).

**Pitfall confirmed:** `batchesApi.ts` has a LOCAL copy of `ValidationOutcome` (lines 14–20), not imported from shared-types. This was flagged in Phase 8 research and hit during Phase 8 Plan 01. Update both the shared schema AND `batchesApi.ts` manually.

### Pattern 6: Backend PATCH Endpoint for Persistence
**What:** The existing GET `/api/v1/batches/{batch_name}/results` reads `checkpoint.json`. There is currently **no write-back endpoint** for edits — all edits live only in Zustand and evaporate on reload. Phase 9 requires durable verification, so a PATCH endpoint must be added.

Confirmed: scanning `batches.py` — no existing PATCH/PUT endpoint for individual results. The `/revalidate` POST only re-runs validation rules without writing user edits.

**New endpoint shape:**
```
PATCH /api/v1/batches/{batch_name}/results/{filename}
Body: { "field": str, "value": str | null, "validation_status": "verified" | "valid" | "invalid" | null }
```

OR bulk form:
```
PATCH /api/v1/batches/{batch_name}/results/{filename}
Body: { "edits": { field: value }, "validation": { field: { "status": "verified" } } }
```

Backend implementation: read `checkpoint.json`, find the entry by `filename`, merge edits and validation status, write back. O(N) scan per call is acceptable for batch sizes ≤ 500.

**No new Pydantic model required for MVP** — use `Dict[str, Any]` body with manual validation. A typed `ResultPatch` model is cleaner but optional.

### Pattern 7: Full-Res Image URL
**What:** `ThumbnailCell.tsx` (line 12) reveals the URL pattern: `/batches-static/{batchName}/{filename}`. This is mounted in `main.py` via FastAPI `StaticFiles(directory=settings.BATCHES_DIR, name="batches-static")`. The same URL works for full-res display — no separate endpoint needed.

```typescript
// ImagePane.tsx
const imageUrl = `/batches-static/${batchName}/${filename}`;
```

Confirmed in `ThumbnailCell.tsx` line 12: `const imageUrl = \`/batches-static/${batchName}/${filename}\`;`

### Pattern 8: Multi-Entry Tab Layout
**What:** For cards with `_entries` JSON array in `data`, the field pane shows tabs. Derived the same way as `ResultsTable.tsx` lines 146–184 (`displayRows` expansion logic).

Detection: `const hasEntries = Boolean(row.data['_entries'])`. Parse into `entries: Record<string, string>[]`. Tab labels: "Entry 1", "Entry 2", ... matching CONTEXT.md decision. Active tab index is local component state (not Zustand — transient per-card state).

Image stays fixed while tabs switch (image belongs to the card, not the entry).

### Pattern 9: Keyboard Shortcut Guard
**What:** `j`/`k`/`v`/`Enter` shortcuts must NOT fire when a text input has focus. Standard guard:

```typescript
// useVerifyKeyboard.ts
const handleKeyDown = (e: KeyboardEvent) => {
  const active = document.activeElement;
  const isEditing =
    active instanceof HTMLTextAreaElement ||
    active instanceof HTMLInputElement;

  if (isEditing) return; // all shortcuts suppressed when editing

  switch (e.key) {
    case 'j': case 'ArrowRight': goNextCard(); break;
    case 'k': case 'ArrowLeft':  goPrevCard(); break;
    case 'v': markCurrentFieldVerified(); break;
    case 'Enter': acceptActiveProposal(); break;
    case 'Escape': /* handled by EditableCell itself */ break;
  }
};

useEffect(() => {
  document.addEventListener('keydown', handleKeyDown);
  return () => document.removeEventListener('keydown', handleKeyDown);
}, [/* deps */]);
```

Attach at document level (not component level) so it works regardless of which sub-element has focus. Clean up on unmount.

**Plain-Enter in textarea vs. Enter-accepts-proposal:** Because the guard `if (isEditing) return` fires first when a textarea is focused, `Enter` inside a textarea inserts a newline (matching Phase 6 EditableCell behavior, `wizardStore` key decision line ~116). The "Enter accepts proposal" shortcut only fires when NO edit is active — correct, no conflict.

### Anti-Patterns to Avoid
- **Don't add cockpit transient state to Zustand partialize:** Active card index, zoom level, current tab index, filter chip selection are ephemeral. Persisting them causes stale state on reload (user returns to wrong card, unexpected zoom). Only `cockpitSplitPercent` should persist.
- **Don't create a new AppView for 'cockpit':** CONTEXT.md locked "optional wizard step after Results". Using a new AppView value would break the wizard step ordering and sidebar step status computation. Keep it as `WizardStep = 'verify'`.
- **Don't use `passive: true` on the wheel event listener:** The zoom handler calls `e.preventDefault()` to stop the container from scrolling. A passive listener throws a console error and ignores `preventDefault`. Use `{ passive: false }`.
- **Don't import ValidationOutcome from shared-types in frontend components:** The frontend uses the local re-export chain `batchesApi.ts → wizardStore.ts`. Keep this chain intact; don't mix import paths or you'll get TS type duplication errors.
- **Don't forget user-select: none during drag-pan:** Without it, text on the page gets selected while the user drags the image. Set `document.body.style.userSelect = 'none'` on mousedown, reset on mouseup.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Full-res image zoom | Custom canvas tile system | CSS `transform: scale + translate` on `<img>` | A5 cards fit in single decode; existing ImagePreview proves pattern works |
| Filmstrip scroll | Virtual scroll / React Window | Native `overflow-x-auto` + `scroll-behavior: smooth` | ≤ 500 thumbnails at 48px each = 24KB DOM — no virtualization needed |
| Drag-handle resize | Resizable panel library | Native `mousedown/mousemove/mouseup` pattern | One file, no dependency |
| Keyboard shortcut routing | Hotkeys library (hotkeys-js, use-hotkeys) | Native `document.addEventListener('keydown')` | Already pattern-matched in codebase; no new dep needed |
| Proposal Accept/Reject in cockpit | Duplicate logic | Reuse existing `acceptCorrectorProposal` / `rejectCorrectorProposal` Zustand actions | Zero new code; same flow as Results |
| Result persistence | New backend storage layer | PATCH into existing `checkpoint.json` | Already the single source of truth; batch_manager pattern is established |

---

## Common Pitfalls

### Pitfall 1: batchesApi.ts Local Type Copy Drifts from Schema
**What goes wrong:** `ValidationOutcome.status` gets `'verified'` added to `batch.schema.json` and regenerated in `generated/ts/index.ts`, but `batchesApi.ts` still has the old union type. TypeScript infers the old type from batchesApi's local copy since `wizardStore.ts` re-exports from there, not from the codegen file.
**Why it happens:** `batchesApi.ts` lines 14–20 define `FieldRule` and `ValidationOutcome` as local interfaces, not imported from `@indexcards/shared-types`. This was an explicit decision during Phase 8 (STATE.md: "ValidationOutcome re-exported through batchesApi.ts into wizardStore.ts").
**How to avoid:** When updating `batch.schema.json`, immediately update `batchesApi.ts` in the same task. Always update both files atomically.
**Warning signs:** TypeScript errors like `Type '"verified"' is not assignable to type '"valid" | "invalid" | "corrected" | "skipped"'`.

### Pitfall 2: Sidebar Step Gating Blocks Cockpit Entry
**What goes wrong:** New `'verify'` step appears in `STEPS` array but `handleStepClick` guard doesn't have a case for it, causing the step to be silently non-clickable.
**Why it happens:** `handleStepClick` in `Sidebar.tsx` has explicit cases for `'processing'` (always blocked) and `'results'` (gated on `batchId`). Any other step falls through to the `getStepStatus === 'complete'` guard. Since `'verify'` is one step after `'results'`, it will be `'pending'` during Results step, so the fallthrough won't allow clicking even after a batch is loaded.
**How to avoid:** Add an explicit case for `'verify'` in `handleStepClick` matching the `'results'` pattern: `if (batchId) setStep('verify')`.
**Warning signs:** Clicking "5. Verify" in sidebar does nothing.

### Pitfall 3: Wheel Event Captured by Outer Scroll Container
**What goes wrong:** The image pane is inside a `main` element with `overflow-y-auto` (MainLayout line 16). Wheel events on the image pane propagate up and scroll the page instead of zooming.
**Why it happens:** Wheel events bubble. If the inner container's wheel handler has `passive: true` (or is not registered with `{ passive: false }`), `e.preventDefault()` is a no-op and the outer scroll wins.
**How to avoid:** Attach the wheel handler via `useEffect` with `{ passive: false }`:
```typescript
const el = containerRef.current;
el.addEventListener('wheel', handleWheel, { passive: false });
```
React's synthetic `onWheel` prop is passive by default in React 17+ — **do not use the JSX prop**. Use `addEventListener` directly.
**Warning signs:** Image doesn't zoom; page scrolls instead.

### Pitfall 4: Partialize List Not Updated for cockpitSplitPercent
**What goes wrong:** Drag-handle position is lost on every page reload even though the code saves it to Zustand, because the field is missing from the `partialize` function.
**Why it happens:** The `partialize` block in `wizardStore.ts` (lines 276–291) is an explicit allowlist. New state fields are NOT persisted unless added there.
**How to avoid:** When adding `cockpitSplitPercent` to the store, add it to `partialize` in the same commit.
**Warning signs:** Drag handle snaps back to 50/50 on reload.

### Pitfall 5: j/k Fire While Typing
**What goes wrong:** Curator types a field value containing the letter "j" or "k". Each keypress jumps to next/previous card, discarding the current edit.
**Why it happens:** Keyboard shortcut listeners at document level capture all keydown events, including those bubbling from textarea inputs.
**How to avoid:** The guard `if (document.activeElement instanceof HTMLTextAreaElement || document.activeElement instanceof HTMLInputElement) return;` must be the FIRST line of the keydown handler. See Pattern 9 above.
**Warning signs:** Card jumps unexpectedly while typing.

### Pitfall 6: PATCH Endpoint Concurrency (Checkpoint.json Write Race)
**What goes wrong:** If the curator rapidly accepts multiple proposals or saves multiple fields in quick succession, concurrent PATCH calls may read stale `checkpoint.json` data and the last writer wins, silently discarding earlier edits.
**Why it happens:** The PATCH implementation reads the full JSON, mutates one entry, then writes back. Two concurrent reads see the same version.
**How to avoid:** For Phase 9 single-curator use (no multi-user), this is acceptable. Debounce PATCH calls from the frontend (300–500ms after last field commit) to coalesce rapid edits into fewer requests. Document the limitation in plan actions.
**Warning signs:** Occasional missing field saves when clicking through cards quickly.

### Pitfall 7: stepOrder Mismatch Between getStepStatus and handleStepClick
**What goes wrong:** `getStepStatus` uses `stepOrder` to compute `'complete'`/`'active'`/`'pending'`. If `'verify'` is appended to stepOrder but not properly handled in `handleStepClick`, the step will show as pending/complete correctly but remain unclickable.
**Why it happens:** Two code paths in `Sidebar.tsx` must both be updated: `stepOrder` array AND `handleStepClick` guard. They're not co-located.
**Warning signs:** Sidebar shows "5. Verify" with correct complete/pending styling, but clicking it does nothing.

---

## Code Examples

Verified patterns from codebase:

### Image URL Pattern (from ThumbnailCell.tsx line 12)
```typescript
const imageUrl = `/batches-static/${batchName}/${filename}`;
```
StaticFiles mount confirmed in `main.py`. Same URL works for full-res cockpit display.

### Existing editedData persistence key for multi-entry rows (from ResultsTable.tsx line 167)
```typescript
filename: `${row.filename}__entry_${idx}`,
```
Phase 9 must use the same `__entry_N` virtual filename pattern when persisting edited values for multi-entry sub-rows, otherwise `updateResultCell` lookups will miss.

### acceptCorrectorProposal Zustand action (from wizardStore.ts lines 249–262)
```typescript
acceptCorrectorProposal: (filename, field) =>
  set((state) => ({
    results: state.results.map((r) => {
      if (r.filename !== filename) return r;
      const proposal = r.validation?.[field]?.corrector_proposal;
      const newEdited = { ...r.editedData };
      if (proposal != null) newEdited[field] = proposal;
      const newValidation = r.validation ? { ...r.validation } : null;
      if (newValidation && newValidation[field]) {
        newValidation[field] = { ...newValidation[field], status: 'valid' };
      }
      return { ...r, editedData: newEdited, validation: newValidation };
    }),
  })),
```
Phase 9 MUST reuse this action. Do not create a parallel accept path in the cockpit. The cockpit calls the same action, which updates `results` in Zustand; the cockpit view re-renders from the updated `results`.

### EditableCell commit behavior (from ResultsTable.tsx lines 71–75)
```typescript
const commit = () => {
  setEditing(false);
  const trimmed = draft.replace(/\n+$/, '');
  if (trimmed !== value) onCommit(trimmed);
};
```
Phase 9's inline edit in the cockpit should replicate this EXACTLY (trailing newline trim, no-op on unchanged value). The `onCommit` in the cockpit additionally triggers a status flip to `'verified'` and debounced PATCH.

### ValidationBadge status cases (from ValidationBadge.tsx lines 25–83)
The existing badge handles `'valid'`, `'invalid'`, `'corrected'`. Phase 9 adds `'verified'`. The new case:
```typescript
} else if (status === 'verified') {
  icon = <CheckCircle2 {...iconProps} className={`${iconProps.className} text-emerald-700`} />;
  tooltipContent = <p className="text-xs text-archive-ink/80">Curator verified.</p>;
}
```
Use `CheckCircle2` (filled double-ring) to distinguish from `valid`'s `CheckCircle` (single ring). Both are available in lucide-react already installed.

### Zustand partialize list (from wizardStore.ts lines 276–291)
```typescript
partialize: (state) => ({
  step: state.step,
  view: state.view,
  files: state.files.map(({ preview: _, ...rest }) => rest),
  fields: state.fields,
  sessionId: state.sessionId,
  batchId: state.batchId,
  promptTemplate: state.promptTemplate,
  selectedTemplateName: state.selectedTemplateName,
  provider: state.provider,
  model: state.model,
  correctorEnabled: state.correctorEnabled,
  correctorCap: state.correctorCap,
  // ADD: cockpitSplitPercent: state.cockpitSplitPercent,
}),
```

`processingState` and `results` are intentionally excluded (performance decision from STATE.md). Keep them excluded. `cockpitSplitPercent` is the only new persisted field.

---

## Key Infrastructure Findings

### What Already Exists (reuse directly)
| Asset | Location | Phase 9 Use |
|-------|----------|-------------|
| `EditableCell` component | `ResultsTable.tsx` lines 46–113 | Extract to shared component or copy into cockpit — same behavior needed |
| `ValidationBadge` component | `features/results/ValidationBadge.tsx` | Extend with `'verified'` case; reuse in cockpit |
| `ValidationFilterChips` | `features/results/ValidationFilterChips.tsx` | Adapt for cockpit filmstrip filter chips (extend `ValidationFilter` type to include `'verified'`) |
| Image URL pattern | `ThumbnailCell.tsx` line 12 | Direct reuse: `/batches-static/${batchName}/${filename}` |
| `acceptCorrectorProposal` / `rejectCorrectorProposal` | `wizardStore.ts` lines 249–273 | Reuse unchanged — same Zustand actions |
| `useResultsQuery` | `batchesApi.ts` lines 153–159 | VerifyStep hydrates the same way as ResultsStep |
| Multi-entry expansion logic | `ResultsTable.tsx` lines 146–184 | Adapt for cockpit — same `_entries` parsing |
| `ImagePreview` zoom/rAF pattern | `features/configure/ImagePreview.tsx` | Reference for `requestAnimationFrame` + `transform3d` approach |
| `WizardNav` | `components/WizardNav.tsx` | Use for "← Back to Results" button at bottom of cockpit |

### What Needs New Backend Code
| Item | Scope | Location |
|------|-------|----------|
| `PATCH /batches/{name}/results/{filename}` | New endpoint | `apps/backend/app/api/api_v1/endpoints/batches.py` |
| `ResultPatch` Pydantic model (optional) | New schema | `apps/backend/app/models/schemas.py` |

### What Needs Schema/Codegen Changes
| Item | File | Change |
|------|------|--------|
| `ValidationOutcome.status` enum | `packages/shared-types/schemas/batch.schema.json` line 24 | Add `"verified"` to enum array |
| Regenerated TS types | `packages/shared-types/generated/ts/index.ts` | Run `turbo generate` |
| Local TS type copy | `apps/frontend/src/api/batchesApi.ts` lines 14–20 | Manual update: add `'verified'` to status union |
| Python schema | `apps/backend/app/models/schemas.py` | `ValidationOutcome.status: str` already accepts any string — no change needed for v1 |

---

## Suggested Wave Breakdown

The planner should consider 3 plans across 2-3 waves:

**Wave 1:**
- **09-01:** Schema + type update (`'verified'` status value, batchesApi.ts update, backend PATCH endpoint, Zustand store extension with `cockpitSplitPercent`). This is the data-model foundation everything else builds on.

**Wave 2 (parallel):**
- **09-02:** Cockpit UI — `VerifyStep.tsx`, `CockpitLayout.tsx` (resize handle), `ImagePane.tsx` (zoom/pan), `Filmstrip.tsx`, routing in `App.tsx` and `Sidebar.tsx`.
- **09-03:** Field interaction — `FieldsPane.tsx` with `EditableCell` integration, `CockpitBadge.tsx` (`'verified'` state), keyboard shortcuts (`useVerifyKeyboard.ts`), multi-entry tabs, PATCH call on commit.

**Wave 3:**
- **09-04:** Entry point wiring — "Verify cards" button in `ResultsStep.tsx`, results → cockpit navigation, exit path back to results, progress indicator ("N/M verified"), export behavior with `'verified'` status (exports already use `editedData` via `fieldValue()` — no export changes needed for the value; verify status is informational metadata for Phase 10/11).

---

## Open Questions

1. **EditableCell extraction strategy**
   - What we know: `EditableCell` is defined inline in `ResultsTable.tsx` (not a standalone component file).
   - What's unclear: Should Phase 9 extract it to `features/results/EditableCell.tsx` for reuse, or copy it into `features/verify/`?
   - Recommendation: Extract to `features/results/EditableCell.tsx` as part of Plan 09-01 (clean shared component). This is a safe refactor since ResultsTable imports it from the same file.

2. **PATCH endpoint — bulk vs. per-field**
   - What we know: Each field commit fires independently (onBlur or Ctrl+Enter).
   - What's unclear: Should the PATCH send one field at a time (more calls, simpler body) or accumulate and send the full row on cockpit exit?
   - Recommendation: Per-field PATCH with 300ms debounce. Simpler, matches the "auto-save on edit" UX. On cockpit exit, fire any pending debounced call immediately.

3. **Export behavior for `'verified'` status**
   - What we know: `fieldValue()` in `useResultsExport.ts` uses `editedData[field] ?? data[field]`. All 8 export functions use `fieldValue()`. Exports already emit the correct (possibly edited) value regardless of validation status.
   - What's unclear: Should exports include a `verification_status` column in CSV/JSON?
   - Recommendation: Defer to Claude during planning. The data value is already correct in exports. Adding status columns is optional enhancement. For Phase 9 MVP, do not modify exports.

4. **Filter chips type extension**
   - What we know: `ValidationFilter` type in `ValidationFilterChips.tsx` is `'all' | 'invalid' | 'corrected' | 'valid'`.
   - What's unclear: Should `'verified'` be added as a cockpit filter option?
   - Recommendation: Yes — cockpit filmstrip needs to filter to "only verified" (so curator can review their own work). Extend `ValidationFilter` to `'all' | 'invalid' | 'corrected' | 'valid' | 'verified'`. The Results `ValidationFilterChips` can silently ignore the new value since the Results view won't show `'verified'` status until Phase 9 runs.

---

## Sources

### Primary (HIGH confidence — codebase verified)
- `apps/frontend/src/store/wizardStore.ts` — Zustand state shape, WizardStep union, partialize list, actions
- `apps/frontend/src/components/Sidebar.tsx` — step registration pattern, handleStepClick guard, stepOrder
- `apps/frontend/src/App.tsx` — step routing switch, AppView handling
- `apps/frontend/src/features/results/ResultsTable.tsx` — EditableCell pattern, multi-entry expansion, ValidationBadge integration
- `apps/frontend/src/features/results/ValidationBadge.tsx` — full badge component with status cases
- `apps/frontend/src/features/results/ResultsStep.tsx` — useResultsQuery hydration, WizardNav wiring
- `apps/frontend/src/features/configure/ImagePreview.tsx` — zoom/rAF/canvas pattern
- `apps/frontend/src/features/results/ThumbnailCell.tsx` — StaticFiles URL pattern
- `apps/frontend/src/api/batchesApi.ts` — local TS type copies (confirmed pitfall), no PATCH endpoint (confirmed gap)
- `apps/backend/app/api/api_v1/endpoints/batches.py` — confirmed no existing edit endpoint
- `apps/backend/app/models/schemas.py` — `ValidationOutcome.status: str` (not enum-constrained)
- `packages/shared-types/schemas/batch.schema.json` — current enum: `["valid", "invalid", "corrected", "skipped"]`
- `apps/frontend/package.json` — installed deps (no new deps needed)

### Secondary (MEDIUM confidence)
- CSS `transform: scale + translate` for browser-native zoom: standard DOM API, no library needed; approach validated by existing `ImagePreview.tsx` use of `transform: translate3d`.
- `{ passive: false }` wheel listener requirement: well-established React/DOM pattern documented by MDN for preventing default scroll.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all needed libraries already installed, confirmed in package.json
- Architecture: HIGH — all insertion points confirmed in codebase with exact line references
- Pitfalls: HIGH — batchesApi.ts drift confirmed as prior Phase 8 issue; wheel passive confirmed by ImagePreview pattern; keyboard guard is standard DOM pattern

**Research date:** 2026-05-18
**Valid until:** 2026-06-18 (codebase stable; only stale if deps major-version bumped)
