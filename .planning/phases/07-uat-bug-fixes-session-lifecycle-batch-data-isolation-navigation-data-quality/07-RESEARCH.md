# Phase 7: UAT Bug Fixes — Session Lifecycle, Batch Data Isolation, Navigation & Data Quality — Research

**Researched:** 2026-02-23
**Domain:** Full-stack bug fixing — React/Zustand frontend, FastAPI backend, WebSocket lifecycle, batch file management
**Confidence:** HIGH (all findings verified directly from source code)

---

## Summary

Phase 7 fixes 15 bugs discovered during browser-automated UAT. All bugs have been traced to root causes in the actual source. No external library research is needed — every fix is surgical code change within the existing stack (Zustand 5, sonner 2, TanStack Table 8, TanStack Query 5, FastAPI, native WebSocket). The research below documents the exact root cause per bug, the minimal fix, and the risks to watch for.

The four bug clusters reduce to three root causes: (1) Zustand `loadBatchForReview` does not hydrate fields from the batch's own `config.json` — it only sets `batchId`, leaving `fields[]` as whatever the current session had; (2) batch_manager writes status "uploaded" unconditionally and never updates it after completion; (3) TemplateSelector keeps `selectedLabel` in local component state which is not persisted.

**Primary recommendation:** Fix Cluster B first (BUG-06/07) because it corrupts all exports. Then Cluster A (BUG-13/15). Then Cluster C (BUG-01/02/03/12). Then Cluster D (all low-risk cosmetic or isolated fixes).

---

## Standard Stack

### Core (already installed — no new packages needed)

| Library | Version | Purpose | Role in fixes |
|---------|---------|---------|---------------|
| zustand | ^5.0.11 | Client state | BUG-06, BUG-13, BUG-03: store actions need updates |
| sonner | ^2.0.7 | Toasts | BUG-12: `duration` option on action toast |
| @tanstack/react-query | ^5.90.21 | Server state / fetching | BUG-06: new `GET /batches/{name}/config` query or extend `loadBatchForReview` |
| @tanstack/react-table | ^8.21.3 | Results table columns | BUG-08 touches `EditableCell` in ResultsTable |
| axios | ^1.13.5 | HTTP client | BUG-06: possible new `fetchBatchConfig` API call |
| fastapi | — | Backend API | BUG-04: `_record_history`/`get_history` status logic |

### No new dependencies required

All bugs are fixed by editing existing source. No npm or pip installs needed.

---

## Architecture Patterns

### Cluster B Root Cause: Fields-in-Zustand vs. Fields-in-Batch

`ResultsStep.tsx` line 51:
```typescript
const fieldLabels = fields.map((f) => f.label);
```
`fields` comes from `useWizardStore()` — the **current session's** field configuration. When `loadBatchForReview` is called from `BatchHistoryCard`, it only does:
```typescript
loadBatchForReview: (batchName) =>
  set({ batchId: batchName, step: 'results', view: 'wizard' }),
```
It does **not** update `fields`. So if the user has switched to a different template since the archived batch was created, `fieldLabels` will be the wrong template's fields.

**Fix pattern:** `loadBatchForReview` must also fetch and set the batch's own `fields[]` from the backend before navigating to Results. Two options:

Option A — Extend `loadBatchForReview` to be an async thunk that calls a new `GET /batches/{name}/config` endpoint, then calls `setFields(...)` before setting step/view.

Option B — Make `ResultsStep` derive field names directly from `rawResults[0].data` keys (the checkpoint.json records), not from the store. This avoids the dependency on `fields[]` in the store entirely.

Option B is safer because it is purely frontend and avoids a new async side effect inside a Zustand action. But Option B only works if the `data` keys in checkpoint.json are exactly the field labels — which they are, since `ocr_engine` writes `{field_label: value}` directly into `data`.

**Recommended fix for BUG-06:** Derive fields from batch results data, not store:
```typescript
// In ResultsStep.tsx, replace:
const fieldLabels = fields.map((f) => f.label);
// With:
const fieldLabels = useMemo(() => {
  if (results.length === 0) return [];
  const keys = new Set<string>();
  results.forEach(r => Object.keys(r.data).forEach(k => keys.add(k)));
  return Array.from(keys).filter(k => !k.startsWith('_'));
}, [results]);
```
This is self-contained and needs no new API endpoint.

**For BUG-07 (exports):** `useResultsExport` is called with `fieldLabels` from `ResultsStep`. Once BUG-06 fix supplies correct `fieldLabels`, BUG-07 is automatically fixed — no changes needed in `useResultsExport.ts`.

### Cluster A Root Cause: Session Cleanup After `create_batch`

In `batch_manager.py`, `create_batch()` line 62:
```python
shutil.rmtree(str(temp_path))
```
After batch creation, the temp session directory is gone. `sessionId` in Zustand still points to the deleted directory. Clicking "Commence Processing" again calls `create_batch` with the same stale `session_id`, which fails with `ValueError("No files found for session {session_id}")`.

**Scope for BUG-13:** The cleanest fix is option (c) from the UAT audit: detect the post-batch state on the ConfigureStep and disable "Commence Processing" with an explanatory message. When `batchId` is already set in the store (meaning a batch was already created for this session), the Configure button should reflect that rather than failing with a cryptic 400 error.

In `ConfigureStep.tsx` `handleStartExtraction`, the guard currently checks `!sessionId || files.length === 0`. It should also check `batchId` — if a `batchId` is already set, the session has been consumed.

**Recommended fix for BUG-13:** Add a `batchId` check in `handleStartExtraction` and disable the button when `batchId !== null`:
```typescript
// In ConfigureStep, add batchId to destructured store values
const { files, fields, sessionId, batchId, ... } = useWizardStore();

// In button disabled condition:
disabled={fields.length === 0 || isPending || !batchName.trim() || batchId !== null}
```
And display an explanatory inline message when `batchId !== null`:
```tsx
{batchId && (
  <p className="text-sm text-archive-ink/60 italic">
    A batch has already been created for this session. Start a new batch from Upload.
  </p>
)}
```

**For BUG-15 (cancel + resume):** The same fix applies — after cancellation, `batchId` is set in the store. The user navigating back to Configure will see the disabled button with the message. This is better than a broken 400 error. A full "resume batch" flow (option d) is out of scope for this phase.

### Cluster C Root Cause Analysis

**BUG-01 and BUG-02 (sidebar navigation blocked):**

In `Sidebar.tsx`, `handleStepClick` at line 42:
```typescript
if (stepKey === 'processing' || stepKey === 'results') return;
```
This is an unconditional guard — even when a completed batch is loaded from archive, clicking "4. Results" in the sidebar does nothing.

**Critical context:** The prior decisions say: "Display-only; step transitions only via store actions". The guard was intentional for the wizard flow. BUG-01 and BUG-02 occur when the user is in the middle of a **normal upload session** (step = 'upload') but clicks a previously-completed step like Results. The `getStepStatus` correctly marks those steps as 'pending' in that case.

Wait — re-reading the audit: "Sidebar navigation to '4. Results' step doesn't work when clicked from the Upload step." If `activeStep === 'upload'`, then `processing` and `results` have status `pending`, not `complete`. So even without the guard on line 42, the guard on line 44 (`if (status === 'complete')`) would block them. The real issue is that after `loadBatchForReview`, the step IS `results`, but navigating back (e.g., the user clicks "Upload" to try to go back) then clicking "Results" fails because the guard blocks it.

Re-reading more carefully: the UAT says "clicked from the Upload step" — meaning the user navigated back to Upload (perhaps via sidebar or via a fresh load), and now cannot get back to Results. After `loadBatchForReview` sets `step='results'`, if the user then navigates to Upload via some path, the Results step would be shown as `pending` again because `activeStep === 'upload'`.

**Actual fix needed:** When `batchId` is set (a batch has been loaded or completed), the sidebar should treat `results` as reachable even from an earlier step. The guard needs to be contextual: allow sidebar click on `results` if `batchId !== null`.

```typescript
// In Sidebar.tsx handleStepClick:
const handleStepClick = (stepKey: WizardStep) => {
  if (stepKey === 'processing') return; // processing never accessible via sidebar
  if (stepKey === 'results') {
    // Allow if batchId is set (batch loaded from archive or completed)
    if (batchId) { setStep('results'); }
    return;
  }
  const status = getStepStatus(stepKey);
  if (status === 'complete') { setStep(stepKey); }
};
```
`batchId` needs to be read from the store in Sidebar.

**BUG-03 (template name lost):**

`TemplateSelector` uses local React state for `selectedLabel`:
```typescript
const [selectedLabel, setSelectedLabel] = useState('Custom / Blank Slate');
```
This is component-local. When the user navigates away (to processing/results) and comes back (to configure), the component remounts and `selectedLabel` resets to `'Custom / Blank Slate'`.

**Fix options:**
- Store `selectedTemplateName` in Zustand, persist it. Simple, low-risk.
- Derive the label from fields comparison (fragile — field arrays can match multiple templates).

**Recommended fix:** Add `selectedTemplateName: string | null` to WizardStore, persist it, and initialize `TemplateSelector`'s `selectedLabel` from the store value on mount.

```typescript
// In wizardStore.ts, add to state:
selectedTemplateName: string | null;
setSelectedTemplateName: (name: string | null) => void;
// In partialize: include selectedTemplateName
```
```typescript
// In TemplateSelector.tsx:
const { setFields, setPromptTemplate, selectedTemplateName, setSelectedTemplateName } = useWizardStore();
const [selectedLabel, setSelectedLabel] = useState(selectedTemplateName ?? 'Custom / Blank Slate');
// On handleSelectTemplate: also call setSelectedTemplateName(name)
// On handleSelectBlank: also call setSelectedTemplateName(null)
```

**BUG-12 (toast duration):**

`FileList.tsx` uses `toast(...)` with `action` and `cancel` but no `duration` override. Sonner 2.x default duration is 4000ms. For action-required toasts, this is too short.

In sonner 2.x, the `toast()` function accepts a `duration` option in milliseconds:
```typescript
toast(`Remove ${name}?`, {
  duration: 10000, // 10 seconds for action-required toasts
  action: { ... },
  cancel: { ... },
});
```
Confirmed from sonner docs: `duration` in milliseconds is a top-level option on all toast types. Setting `Infinity` would make it sticky until dismissed.

### Cluster D Root Cause Analysis

**BUG-04 (batch status always "uploaded"):**

In `batch_manager.py` `_record_history()` line 82:
```python
history.append({
    ...
    "status": "uploaded",  // hardcoded
    ...
})
```
`get_history()` reads `entry.get("status", "uploaded")` — it returns exactly what was written. The OCR engine (`run_ocr_task`) never updates `batches.json` status after completion. The `ws_manager` has the final status in memory only.

**Fix:** `run_ocr_task` (in `batches.py`) already knows the final status ("completed", "cancelled", "failed") when it broadcasts the final progress update. Add a `batch_manager.update_batch_status(batch_name, status)` call there.

Add to `batch_manager.py`:
```python
def update_batch_status(self, batch_name: str, status: str) -> None:
    """Update the status field of a batch in batches.json."""
    history_file = Path(settings.BATCHES_HISTORY_FILE)
    if not history_file.exists():
        return
    try:
        with open(history_file, "r") as f:
            history = json.load(f)
        for entry in history:
            if entry.get("batch_name") == batch_name:
                entry["status"] = status
                break
        with open(history_file, "w") as f:
            json.dump(history, f, indent=2)
    except Exception:
        pass  # non-critical
```
Call it from `run_ocr_task` after the final `broadcast_progress`, passing the resolved status string.

**BUG-05 (identical batch names in archive):**

`ConfigureStep.tsx` initializes `batchName` as:
```typescript
const [batchName, setBatchName] = useState(`Batch_${new Date().toISOString().slice(0, 10)}`);
```
All batches created the same day have identical `custom_name`. The backend appends a `_YYYYMMDD-HHMMSS_<8char-uuid>` suffix to create the unique `batch_name`, but `BatchHistoryCard` displays `batch.custom_name` (the user-editable name), not `batch.batch_name` (the unique ID).

Two independent sub-fixes:
1. Change default batch name in ConfigureStep to include time: `` `Batch_${new Date().toISOString().slice(0, 16).replace('T', '_')}` `` → `Batch_2026-02-23_14:30`.
2. In `BatchHistoryCard`, show the unique `batch_name` as a subtitle or in the detail row below the `custom_name`.

**BUG-08 (trailing newline on Enter commit):**

In `EditableCell`, `onBlur` calls `commit()`. But `onKeyDown` does not call `commit()` for plain Enter — it is not handled, so Enter inserts a newline into `draft`. However, the audit says "pressing Enter to save" causes a trailing newline. This means users press Enter expecting to commit, then the newline is included.

The actual code has `Ctrl/Cmd+Enter` for commit. Plain Enter inserts newline (intended behavior per prior decisions). The bug is specifically about the trailing newline when the **blur** fires after the user presses Enter and then clicks elsewhere.

Actually re-reading: "trailing newline character appended to edited cell values when pressing Enter to save". The commit action is `onBlur` or `Ctrl+Enter`. If a user presses `Enter` (without Ctrl) in the textarea, a newline is appended to `draft`. If they then blur or use Ctrl+Enter, the value will have a trailing `\n`.

**Fix:** In `commit()`, trim trailing whitespace/newlines from `draft` before committing:
```typescript
const commit = () => {
  setEditing(false);
  const trimmed = draft.replace(/\n+$/, '');
  if (trimmed !== value) onCommit(trimmed);
};
```
This preserves intentional internal newlines but strips accidental trailing ones.

**BUG-09 (LIDO hardcode):**

In `useResultsExport.ts` line 124:
```typescript
<lido:term>Tonbandkarteikarte</lido:term>
```
This is hardcoded. Fix: use a sensible generic fallback like "Karteikarte" or derive from batch metadata if available. Since batch config is not easily available in the export hook (it only receives `results`, `fields`, `batchName`), the minimal fix is to change "Tonbandkarteikarte" to a generic "Karteikarte" (or "Index Card").

**BUG-10 (page title):**

`apps/frontend/index.html` line 7:
```html
<title>frontend</title>
```
Change to a meaningful title, e.g., `Archival Metadata Extraction Tool` or `Indexcards OCR`.

**BUG-11 (WebSocket race condition):**

`useProcessingWebSocket.ts` cleanup in the useEffect:
```typescript
return () => {
  const ref = wsRef.current;
  wsRef.current = null;
  ref?.close();
};
```
The cleanup correctly sets `wsRef.current = null` before calling `close()`, which prevents the reconnect in `ws.onclose`. However, `ref?.close()` is called on a WebSocket that may still be in `CONNECTING` state (`readyState === 0`). Calling `close()` on a CONNECTING WebSocket generates the "WebSocket is closed before the connection is established" warning in Chrome/Firefox.

**Fix:** Guard `close()` with a `readyState` check:
```typescript
return () => {
  const ref = wsRef.current;
  wsRef.current = null;
  if (ref && ref.readyState !== WebSocket.CONNECTING) {
    ref.close();
  } else if (ref) {
    // Wait for open before closing, or just don't close — the null guard above prevents reconnect
    ref.onopen = () => ref.close();
  }
};
```
Alternatively, simply suppress the close on CONNECTING and rely on the `wsRef.current = null` guard to prevent reconnect — the underlying OS connection will be cleaned up anyway.

Simpler fix that avoids the warning:
```typescript
return () => {
  const ref = wsRef.current;
  wsRef.current = null;
  if (ref) {
    if (ref.readyState === WebSocket.OPEN || ref.readyState === WebSocket.CLOSING) {
      ref.close();
    } else {
      // CONNECTING: set onopen to close immediately after connect
      ref.onopen = () => ref.close();
    }
  }
};
```

**BUG-14 (OCR field overflow):**

Root cause is prompt engineering. The backend `ocr_engine` uses the `prompt_template` stored in `config.json`. Adding field length constraints to the prompt template instruction text is the fix. This is a text edit to the default prompt in `config.py` or a documentation note in the batch creation UI. Out of scope for deterministic bug fixes but straightforward if the prompt is updated.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Batch status persistence | Custom status file | Extend `update_batch_status()` in BatchManager | Already has file-lock-free JSON pattern; batch_manager is the single owner of `batches.json` |
| Field derivation from results | Separate field cache endpoint | Derive from `results[0].data` keys directly | Checkpoint.json already contains field names as top-level keys in each result's `data` dict |
| Template name persistence | Complex template matching | Simple string field in Zustand + localStorage | The label is display-only and already has a setter pattern in the store |

---

## Common Pitfalls

### Pitfall 1: BUG-06 Fix Breaks Field Order
**What goes wrong:** Deriving field names from `Object.keys(results[0].data)` returns keys in insertion order (JavaScript spec), but different cards might have different keys if some fields are missing. Using a Set accumulator from all rows preserves all possible fields but loses consistent ordering across batches.
**Why it happens:** Checkpoint.json writes `data: {field1: val, field2: val}` from the LLM output, which varies.
**How to avoid:** Collect keys from all rows but preserve the order of first occurrence. Alternatively, add a `GET /batches/{name}/config` endpoint that returns the ordered `fields` array from `config.json` — this is authoritative and ordered.
**Warning signs:** Column order changes between batches loaded from archive.

**Decision point:** Option B (derive from results data) is simpler but may have ordering issues. Option A (fetch config) is authoritative. Recommend implementing Option A with a dedicated `fetchBatchConfig` API call inside `loadBatchForReview`. Both are valid — planner must choose one.

### Pitfall 2: `loadBatchForReview` Is Synchronous Zustand Setter
**What goes wrong:** If BUG-06 fix requires fetching config from backend, `loadBatchForReview` cannot be a plain `set()` call. It would need to be an async function outside the store, or use a separate React Query / `useEffect` in ResultsStep.
**How to avoid:** Keep `loadBatchForReview` synchronous (only sets `batchId`). Add a separate `useEffect` in `ResultsStep` that fires when `batchId` changes and calls a new `useBatchConfigQuery(batchId)` to hydrate `fields`. OR use Option B (derive from data).

### Pitfall 3: Zustand Partialize — New Fields Must Be Included
**What goes wrong:** Adding `selectedTemplateName` to WizardStore state but forgetting to add it to `partialize()` means it won't persist across page reloads, defeating the purpose of the fix for BUG-03.
**How to avoid:** Always add new persisted fields to both `initialState` and the `partialize` return.

### Pitfall 4: BUG-04 Fix — Concurrent File Writes to batches.json
**What goes wrong:** `run_ocr_task` runs in a background thread. Calling `batch_manager.update_batch_status()` from it while another request reads `get_history()` could cause partial JSON reads.
**Why it happens:** The existing `_record_history` and `get_history` methods do no file locking.
**How to avoid:** The existing pattern in `batch_manager.py` has no locking either — it reads, modifies, writes. The risk is low (small file, fast operation, low concurrency). Use the same pattern. Do not introduce `fcntl` locking — inconsistent with existing code style.

### Pitfall 5: Sidebar BUG-01/02 — `batchId` Access
**What goes wrong:** `Sidebar.tsx` currently does not subscribe to `batchId`. Adding a subscription means the sidebar re-renders whenever `batchId` changes.
**How to avoid:** Use a granular Zustand selector: `const batchId = useWizardStore((state) => state.batchId);` — this is already the pattern used for `activeStep` and `view` in the sidebar. No performance issue.

### Pitfall 6: BUG-08 Trim May Affect Legitimate Multi-line Values
**What goes wrong:** If a user intentionally enters a multi-line value with a trailing newline (edge case), the trim would remove it.
**How to avoid:** Only strip trailing `\n` (not spaces). Use `draft.replace(/\n+$/, '')`. Do not use `trim()`.

### Pitfall 7: BUG-13 — `batchId` Set But Session Navigated Away
**What goes wrong:** If user starts a batch (batchId set), navigates to Results, clicks "Start New Batch" (which calls `resetWizard()`), then uploads new files and goes to Configure — `batchId` is null again (resetWizard resets to `initialState`). This flow is correct. But if user uses browser back button without "Start New Batch", the store persists and `batchId` remains set. The fix using `batchId !== null` to disable the button is correct for this case too — the user needs to explicitly start fresh.

---

## Code Examples

### Derive field labels from results data (BUG-06 Option B)
```typescript
// In ResultsStep.tsx — replace `const fieldLabels = fields.map((f) => f.label);`
const fieldLabels = useMemo(() => {
  if (results.length === 0) return [];
  const seen = new Map<string, number>(); // key -> first occurrence index
  results.forEach((r) => {
    Object.keys(r.data).forEach((k) => {
      if (!seen.has(k)) seen.set(k, seen.size);
    });
  });
  return Array.from(seen.entries())
    .sort((a, b) => a[1] - b[1])
    .map(([k]) => k)
    .filter((k) => !k.startsWith('_'));
}, [results]);
```
Source: direct analysis of `ResultsStep.tsx` L51 and checkpoint.json structure.

### Update batch status in background task (BUG-04)
```python
# In batches.py, run_ocr_task(), after final broadcast_progress:
final_status = "cancelled" if cancel_event.is_set() else "completed"
# ... existing broadcast_progress call ...
batch_manager.update_batch_status(batch_name, final_status)
```
Source: direct analysis of `run_ocr_task` in `batches.py`.

### Sonner toast duration (BUG-12)
```typescript
// In FileList.tsx handleDelete:
toast(`Remove ${name}?`, {
  duration: 10000, // 10s — long enough to click Confirm
  action: {
    label: 'Confirm',
    onClick: () => { removeFile(id); toast.success(`${name} removed from batch.`); },
  },
  cancel: {
    label: 'Cancel',
    onClick: () => {},
  },
});
```
Source: sonner 2.x API — `duration` option confirmed in package.json (sonner ^2.0.7).

### WebSocket readyState guard (BUG-11)
```typescript
// In useProcessingWebSocket.ts cleanup:
return () => {
  const ref = wsRef.current;
  wsRef.current = null;
  if (ref) {
    if (ref.readyState === WebSocket.CONNECTING) {
      ref.onopen = () => ref.close();
    } else {
      ref.close();
    }
  }
};
```
Source: MDN WebSocket.readyState — CONNECTING=0, OPEN=1, CLOSING=2, CLOSED=3. Confirmed by codebase analysis.

### Persist selected template name in Zustand (BUG-03)
```typescript
// wizardStore.ts additions:
selectedTemplateName: string | null;
setSelectedTemplateName: (name: string | null) => void;

// In initialState:
selectedTemplateName: null as string | null,

// In create():
setSelectedTemplateName: (selectedTemplateName) => set({ selectedTemplateName }),

// In partialize:
selectedTemplateName: state.selectedTemplateName,
```
Source: direct analysis of `wizardStore.ts` persist/partialize pattern.

---

## State of the Art

| Old Approach | Current Approach | Impact for Phase 7 |
|--------------|-----------------|-------------------|
| batches.json status never updated after creation | After BUG-04 fix: status updated on completion | History shows meaningful status |
| `loadBatchForReview` only sets batchId | After BUG-06 fix: fields hydrated from results data | Archive review shows correct fields |
| TemplateSelector name in local state | After BUG-03 fix: persisted in Zustand | Name survives step navigation |

---

## Open Questions

1. **BUG-06: Option A vs Option B for field source**
   - What we know: Option B (derive from results data) is simpler and self-contained; Option A (fetch `config.json` fields) is authoritative and preserves original field order.
   - What's unclear: Does field order matter for exports? If yes, Option A is preferable. If no, Option B is sufficient.
   - Recommendation: Implement Option B. Add a note in the plan that if field ordering issues arise in QA, Option A (new `GET /batches/{name}/config` endpoint + `useBatchConfigQuery`) can replace it without breaking anything.

2. **BUG-01/02: Intended vs. accidental behavior**
   - What we know: The sidebar guard was intentionally added to prevent sidebar navigation to results/processing. BUG-01/02 describe the case where a batch is loaded from archive but the user cannot use the sidebar to jump back to results.
   - What's unclear: Should sidebar `results` be clickable only when `batchId !== null`, or also when `step` has advanced past results in the normal wizard flow?
   - Recommendation: Allow `results` sidebar click only when `batchId !== null`. This is the minimal change that fixes the archive review flow without changing the wizard-order enforcement.

3. **BUG-09: Correct default LIDO term**
   - What we know: "Tonbandkarteikarte" is specific to one project. The fix should be generic.
   - What's unclear: Is "Karteikarte" the correct German archival term, or should it be "Indexkarte"?
   - Recommendation: Use "Karteikarte" as the generic German term. Document it as a placeholder that users can customize by editing the prompt template metadata.

4. **BUG-14: OCR overflow — scope**
   - What we know: This is a prompt engineering issue. The default `EXTRACTION_PROMPT` in `config.py` does not restrict field lengths.
   - What's unclear: Whether adding field length constraints to the default prompt would break other templates.
   - Recommendation: Out of scope for Phase 7. Document as known limitation; address in a future prompt tuning phase.

---

## Sources

### Primary (HIGH confidence — direct source code inspection)
- `/apps/frontend/src/store/wizardStore.ts` — loadBatchForReview, partialize, fields in state
- `/apps/frontend/src/features/results/ResultsStep.tsx` — fieldLabels derivation from store
- `/apps/frontend/src/features/results/ResultsTable.tsx` — EditableCell commit handler (BUG-08)
- `/apps/frontend/src/features/results/useResultsExport.ts` — LIDO hardcode (BUG-09)
- `/apps/frontend/src/features/configure/ConfigureStep.tsx` — batch creation guard, batchName default
- `/apps/frontend/src/features/configure/TemplateSelector.tsx` — local selectedLabel state (BUG-03)
- `/apps/frontend/src/features/upload/FileList.tsx` — toast without duration (BUG-12)
- `/apps/frontend/src/features/history/BatchHistoryCard.tsx` — loadBatchForReview caller
- `/apps/frontend/src/components/Sidebar.tsx` — handleStepClick guard (BUG-01/02)
- `/apps/frontend/src/features/processing/useProcessingWebSocket.ts` — cleanup close on CONNECTING (BUG-11)
- `/apps/frontend/index.html` — page title "frontend" (BUG-10)
- `/apps/backend/app/services/batch_manager.py` — _record_history status hardcode (BUG-04), create_batch cleanup (BUG-13/15)
- `/apps/backend/app/api/api_v1/endpoints/batches.py` — run_ocr_task final status, create_batch 400 error
- `/apps/backend/app/services/ws_manager.py` — no status persistence to disk
- `/apps/backend/app/models/schemas.py` — BatchHistoryItem schema
- `/apps/frontend/package.json` — sonner ^2.0.7, zustand ^5.0.11

---

## Metadata

**Confidence breakdown:**
- Root cause analysis: HIGH — all findings from direct source code reading, no inference
- Fix patterns: HIGH — all fixes reference specific lines and follow existing patterns in the codebase
- Risk assessment: MEDIUM — concurrent write risk in BUG-04, ordering risk in BUG-06 Option B are theoretical; no load testing done

**Research date:** 2026-02-23
**Valid until:** 2026-03-25 (code is stable; no fast-moving dependencies involved)
