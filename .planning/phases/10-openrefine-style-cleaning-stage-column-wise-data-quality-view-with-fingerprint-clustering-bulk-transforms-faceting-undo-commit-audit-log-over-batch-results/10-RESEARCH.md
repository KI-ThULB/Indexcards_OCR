# Phase 10: OpenRefine-style Cleaning Stage - Research

**Researched:** 2026-05-18
**Domain:** Frontend-heavy data cleaning UI with client-side algorithms, audit persistence, and backend endpoint extension
**Confidence:** HIGH (all findings verified against live codebase; no external library dependencies needed)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Workflow placement & scope:**
- Clean is the **6th wizard step**, optional, opt-in. Order: Upload → Configure → Processing → Results → Verify → Clean.
- Entry points: "Clean columns" buttons on **both** Results and Verify steps (mirrors Phase 9's "Verify cards" placement).
- Layout: **column-list sidebar + main column workspace**. Left sidebar lists all extracted fields with per-field row count and unique-value count; clicking a field activates it in the main pane.
- Column scope: all extracted fields are cleanable by default; each row in the sidebar has a hide affordance (hidden columns remain in the data, just not in the cleaning UI).
- Edit overlap with Verify: both write to the same `editedData` map through the same PATCH endpoint. The audit log records the **source** of each change (`vlm-original`, `cockpit-edit`, `bulk-transform`, `cluster-merge`) as provenance. Last write wins.
- Multi-entry rows (Findmittel `_entries`): **each entry is its own row** in column view. A 3-entry card contributes 3 rows; bulk transforms apply per-row.
- Audit log UX: **collapsible side/bottom panel**, persistent across column switches, most recent on top, per-entry Undo button. Always visible (collapsible when cramped). Mirrors OpenRefine's history panel.
- Auto-actions: none. Nothing runs automatically on view entry or column open. Every operation requires explicit curator action.

**Clustering & faceting mechanics:**
- Algorithm: **fingerprint only** for v1 (Unicode-aware: NFKD/NFC + casefold + strip-punct + strip-diacritics + sort tokens + join).
- Compute location: **frontend, client-side** over already-hydrated `results` from `useResultsQuery`. No new clustering endpoint.
- Cluster picker UI: **table** — one row per cluster, columns: cluster id / variant values (comma-joined) / row count / suggested canonical value (editable text input, pre-filled with most common variant) / Apply / Skip.
- Faceting: **text facet** (unique-values list with counts, click-to-filter, multi-select) **AND pattern facet** (filter rows whose value matches a regex). Numeric/date/scatter facets deferred.

**Bulk transforms & undo/commit:**
- v1 transforms (7): Trim, Upper, Lower, Title Case, Collapse-whitespace, Regex Replace (modal with find/replace inputs supporting capture groups), Set-to-NULL.
- Row scope: the **currently faceted rows in the active column**. If no facet active, the entire column.
- Undo: **per-operation stack, unlimited within session**, in-memory. Every transform, cluster merge, or cell edit pushes an entry; clicking Undo on any audit entry reverts that operation. Stack evaporates on reload.
- Persistence: **autosave via debounced PATCH (~500ms)** through the existing `PATCH /results/{filename}` endpoint.
- Audit log lifetime: **persisted server-side in `checkpoint.json`** alongside results. PATCH endpoint accepts an `audit_entry` field that gets appended server-side.

**Status integration with Phase 8/9:**
- Validation status on bulk transform: **re-run client-side validation on the new value**.
- `verified` status preservation: **keep `verified` only if the value didn't change**.
- Validation runtime: **TypeScript port of the Phase 8 regex + vocab rules** shipped client-side.
- Export gate: **reuse the existing Phase 8 soft-block gate unchanged**.

### Claude's Discretion
- Exact sidebar dimensions, sidebar layout (text size, count badges), and column-row hover affordances
- Position and width of the audit-log panel (side vs bottom), collapse animation, max visible entries before scrolling
- Default sort order in the cluster picker table (likely by affected row count, descending)
- Canonical-value heuristic in the cluster picker (most common variant; could be smarter)
- Regex flavor for both Regex Replace and pattern facet (JS regex is implied)
- Title Case rules (locale-aware? articles like "von" / "the" handled?)
- Audit log entry shape (timestamp / op / details)
- Empty-state copy when no clusters/facets/transforms have run yet
- Exact debounce ms (500ms baseline acceptable)
- Whether the audit log panel re-loads its contents from `checkpoint.json` on view entry
- Confirmation prompt for destructive transforms over very large row counts (>1000 rows)

### Deferred Ideas (OUT OF SCOPE)
- n-gram fingerprint, Levenshtein-similarity, phonetic clustering
- GREL-like expression language for custom transforms
- Numeric / date / scatter facets
- Cross-session undo
- Cross-column transforms
- Confirmation prompt for very large operations (flagged as possible polish — Claude's discretion above)
- Audit log export as separate artifact
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| FR4 | Results Visualization & Export — summary view, downloadable data, CSV/XML export | Phase 10 is a new view over extracted data; export gate reuses existing `checkValidationGate` from `useResultsExport.ts` |
| FR2 | Metadata Field Configuration — users define fields to extract | Column-wise cleaning operates per-field; field list comes from `fieldLabels` derived from `results` in `ResultsStep.tsx` |
| FR5 | Local Storage / Persistence — results stored locally in `output_batches/` | Audit log persisted server-side in `checkpoint.json` alongside existing results; same batch directory |

Primary: FR4. Secondary: FR2, FR5.
</phase_requirements>

---

## Summary

Phase 10 is a frontend-heavy phase with one minimal backend extension. The existing infrastructure (WizardStep union, Sidebar step routing, Zustand `results` store, `useResultsQuery` hook, PATCH endpoint, `checkValidationGate` export gate, Phase 8 validation normalization) provides almost everything needed — Phase 10 stitches these together into a new 'clean' wizard step.

The only backend change is extending `ResultPatch` (schemas.py) to accept an optional `audit_entry` field and appending it server-side to an `audit` array at the top level of `checkpoint.json`. This changes the checkpoint format from a flat JSON array to a JSON object `{results: [...], audit: [...]}`. This is a breaking structural change that affects `get_batch_results`, `patch_result`, `revalidate_batch`, and `retry-image` — all four endpoints read or write checkpoint.json and must be updated together in Wave 1.

The client-side fingerprint algorithm is a TypeScript port of the exact normalization already used in `vocab_rules.py`'s `normalize_value` function plus token-sort-join. The TS port must match byte-for-byte so that cluster membership and Phase 8 vocabulary validation agree on the same strings. The NFKD/NFC casefold + strip-combining-marks pipeline is documented precisely below.

The undo stack requires snapshotting per-cell `before` state for every bulk transform — not just the operation description. A 7-transform × 500-row worst case means up to 3,500 string entries per undo entry, which is acceptable in-memory but must never be stored in `localStorage` (already excluded from Zustand partialize).

**Primary recommendation:** Plan Wave 1 as a schema-first wave (checkpoint migration + endpoint updates + WizardStep 'clean' + TS normalization util), then Wave 2 in parallel (CleanStep shell + clustering) before Wave 3 (transforms + undo + export hookup + integration polish).

---

## Standard Stack

### Core (all already installed — zero new npm dependencies)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| React + TypeScript | 19.2 / ~5.9.3 | UI component tree | Project standard |
| Zustand 5.0.11 | 5.0 | State management (results, editedData, undo stack) | Project standard |
| TanStack Query 5.90 | 5.x | `useResultsQuery` data fetch on mount | Project standard |
| Axios | 1.13 | PATCH calls for autosave and audit_entry | Project standard |
| Tailwind 3.4 | 3.4 | Styling (JIT, static class maps for status colors) | Project standard — locked at 3.4 |
| Lucide React 0.575 | 0.575 | Icons (Scissors, FlipHorizontal, Search, etc.) | Project standard |
| Sonner 2.0.7 | 2.0 | Toast for export gate and large-operation confirmation | Project standard |

**Installation:** No new packages needed. Phase 10 is pure composition of existing stack.

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Built-in `String.prototype` | Web platform | `toUpperCase`, `toLowerCase`, `trim`, `replace` | Transforms |
| `Intl.Segmenter` or custom title-case | Web platform | Title Case word-boundary detection | Title Case transform — see pattern section |
| `String.normalize('NFC'/'NFD'/'NFKD')` | Web platform | Unicode normalization for fingerprint | Fingerprint algorithm |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Client-side fingerprint | Server-side clustering endpoint | Server round-trip on every threshold change; not needed since data already hydrated |
| `checkpoint.json` object wrapper `{results:[...],audit:[...]}` | Separate `audit.json` file | Two-file approach avoids checkpoint migration but adds a new file to manage in delete_batch, history list, StaticFiles mount — object wrapper is cleaner and matches Phase 9 precedent |

---

## Architecture Patterns

### Recommended File Structure

```
apps/frontend/src/features/clean/
├── CleanStep.tsx              # 6th wizard step root — column-list sidebar + main workspace layout
├── ColumnList.tsx             # Left sidebar: field rows with row count + unique count + hide toggle
├── ColumnWorkspace.tsx        # Right pane: ClusterPicker + FacetPanel + TransformBar + AuditPanel
├── ClusterPicker.tsx          # Table of fingerprint clusters (variants / row count / canonical input / Apply/Skip)
├── FacetPanel.tsx             # TextFacet (value list) + PatternFacet (regex input) tabs
├── TransformBar.tsx           # 7 transform buttons + Regex Replace modal
├── AuditPanel.tsx             # Collapsible panel: list of audit entries with per-entry Undo button
├── useCleanState.ts           # Local hook: activeColumn, facet state, undo stack, hiddenColumns
└── fingerprint.ts             # Pure TS: computeFingerprint(value), buildClusters(rows, field)
```

### Pattern 1: WizardStep 'clean' — exact insertion points

**What:** Add 'clean' to the WizardStep union type and all step-order arrays. Phase 9 demonstrates the exact same operation for 'verify'.

**Four files to update in Wave 1:**

1. `apps/frontend/src/store/wizardStore.ts` — line 6:
   ```typescript
   // BEFORE
   export type WizardStep = 'upload' | 'configure' | 'processing' | 'results' | 'verify';
   // AFTER
   export type WizardStep = 'upload' | 'configure' | 'processing' | 'results' | 'verify' | 'clean';
   ```

2. `apps/frontend/src/components/Sidebar.tsx` — STEPS array (line 15-21):
   ```typescript
   // Add after verify entry:
   { key: 'clean', label: '6. Clean', icon: <Scissors size={18} /> },
   // Also add 'clean' to stepOrder array (line 33) and handleStepClick guard (mirrors verify guard):
   if (stepKey === 'clean') {
     if (batchId) { setStep('clean'); }
     return;
   }
   // Also add 'clean' to isClickable condition (line 114):
   (step.key === 'clean' && !!batchId)
   ```

3. `apps/frontend/src/App.tsx` — renderContent switch block:
   ```typescript
   case 'clean':
     return <CleanStep />;
   ```
   Also add: `import { CleanStep } from './features/clean/CleanStep';`

4. `apps/frontend/src/store/wizardStore.ts` — `getStepStatus` stepOrder array in Sidebar.tsx (line 33):
   ```typescript
   const stepOrder: WizardStep[] = ['upload', 'configure', 'processing', 'results', 'verify', 'clean'];
   ```

**Critical:** The 'clean' step must appear in BOTH the `WizardStep` union AND the `stepOrder` array in Sidebar. Phase 9 hit this exact issue; the fix was in both files.

### Pattern 2: checkpoint.json Format Migration (Wave 1 — BREAKING)

**Current format:** flat JSON array `[{filename, batch, success, data, duration, validation, ...}, ...]`

**New format:** JSON object with two top-level keys:
```json
{
  "results": [{...}, ...],
  "audit": [
    {
      "id": "uuid-or-timestamp-counter",
      "ts": "2026-05-18T09:15:32.412Z",
      "op": "bulk-transform",
      "column": "Künstler",
      "transform": "Upper",
      "affected": 42,
      "scope": "faceted",
      "facet_description": "text:Berlin",
      "source": "bulk-transform"
    }
  ]
}
```

**All affected backend endpoints (all must be updated atomically):**

| Endpoint | File | Change |
|----------|------|--------|
| `GET /batches/{name}/results` | `batches.py` line 325 | Return `data["results"]` when `isinstance(data, dict)` |
| `PATCH /batches/{name}/results/{filename}` | `batches.py` line 187 | Read `checkpoint["results"]`; accept `audit_entry` field in `ResultPatch`; append to `checkpoint["audit"]` |
| `POST /batches/{name}/revalidate` | `batches.py` line 241 | Read `results` from `checkpoint["results"]`; write back full object |
| `POST /batches/{name}/retry-image/{filename}` | `batches.py` line 357 | Filter `checkpoint["results"]`; write back full object |

**schemas.py change (ResultPatch):**
```python
class ResultPatch(BaseModel):
    field: str
    value: Optional[str] = None
    validation_status: Optional[str] = None
    audit_entry: Optional[dict] = None  # NEW: appended to checkpoint["audit"] if provided
```

**Migration strategy:** When reading checkpoint.json, detect format with `isinstance(data, list)`. If list, wrap it: `{"results": data, "audit": []}` and write back before proceeding. This makes all endpoints forward-compatible with old batches.

**Confidence:** HIGH — verified against live batches. Batch `Batch_2026-05-18_06-59_08cceedc/checkpoint.json` is currently a flat list (confirmed in research). The migration guard already exists in `patch_result` (line 207): `rows = checkpoint if isinstance(checkpoint, list) else checkpoint.get("results", [])` — but it doesn't handle audit yet, and it doesn't write back the wrapped format. The Wave 1 plan must harden all four endpoints consistently.

### Pattern 3: Fingerprint Algorithm (TypeScript Port)

**Reference:** `apps/backend/app/services/validation/vocab_rules.py` `normalize_value()`.

The TS fingerprint function must produce identical output to the Python normalization for the same input. The pipeline is:

```typescript
// apps/frontend/src/features/clean/fingerprint.ts

/** Normalize a value for fingerprint comparison.
 * Mirrors Python vocab_rules.normalize_value() exactly.
 * Pipeline: trim → NFC → casefold (toLowerCase) → NFD → strip combining marks → NFC
 */
export function normalizeValue(value: string): string {
  if (!value) return '';
  let v = value.trim();
  v = v.normalize('NFC');
  v = v.toLowerCase();          // JS toLowerCase ≈ Python casefold for Basic Multilingual Plane
  v = v.normalize('NFD');
  v = v.replace(/\p{Mn}/gu, ''); // strip combining marks (Unicode category Mn)
  return v.normalize('NFC');
}

/** Fingerprint for clustering: normalize → tokenize → sort → join.
 * Strips punctuation before tokenizing (OpenRefine fingerprint spec).
 */
export function computeFingerprint(value: string): string {
  const norm = normalizeValue(value);
  // Strip non-alphanumeric/non-space characters
  const stripped = norm.replace(/[^\p{L}\p{N}\s]/gu, '');
  const tokens = stripped.split(/\s+/).filter(Boolean);
  tokens.sort();
  return tokens.join(' ');
}

export interface ClusterGroup {
  fingerprint: string;
  values: string[];          // all distinct raw values with this fingerprint
  rowCount: number;          // total rows across all variants
  canonical: string;         // pre-filled suggestion (most common variant)
}

/** Build fingerprint clusters for a given column across all display rows. */
export function buildClusters(
  rows: DisplayRow[],
  field: string
): ClusterGroup[] {
  const fpMap = new Map<string, { values: Map<string, number>; rowCount: number }>();
  for (const row of rows) {
    const raw = row.editedData[field] ?? row.data[field] ?? '';
    if (!raw) continue;
    const fp = computeFingerprint(raw);
    if (!fpMap.has(fp)) fpMap.set(fp, { values: new Map(), rowCount: 0 });
    const entry = fpMap.get(fp)!;
    entry.values.set(raw, (entry.values.get(raw) ?? 0) + 1);
    entry.rowCount++;
  }
  // Only return clusters with 2+ distinct values (i.e., actual near-duplicates)
  return [...fpMap.entries()]
    .filter(([, e]) => e.values.size >= 2)
    .map(([fp, e]) => {
      const sorted = [...e.values.entries()].sort((a, b) => b[1] - a[1]);
      return {
        fingerprint: fp,
        values: sorted.map(([v]) => v),
        rowCount: e.rowCount,
        canonical: sorted[0][0], // most frequent variant
      };
    })
    .sort((a, b) => b.rowCount - a.rowCount); // highest impact first
}
```

**Python casefold vs JS toLowerCase:** Python `casefold()` handles German ß → ss, Turkish İ → i, etc. JavaScript's `toLowerCase()` does NOT handle ß → ss (ß stays ß). For the project's archival use case this is LOW risk but should be documented. If a curator has "STRASSE" and "Straße", Python would fingerprint-equal them while JS would not. The planner should flag this as a known divergence and decide whether to add a manual ß→ss substitution step. Recommendation: add `v = v.replace(/ß/g, 'ss');` after `toLowerCase()` to match Python casefold for the most common German case.

**Confidence:** HIGH — normalization pipeline read directly from `vocab_rules.py`; Unicode APIs verified.

### Pattern 4: Undo Stack Design

The undo stack is an in-memory array stored in `useCleanState.ts` local state (NOT Zustand, NOT localStorage — deliberately ephemeral).

Each undo entry must capture per-cell before-state:

```typescript
interface UndoEntry {
  id: string;                              // stable ID for AuditPanel row key
  ts: string;                              // ISO timestamp
  op: 'bulk-transform' | 'cluster-merge'; // operation type
  column: string;                          // field name
  label: string;                           // human-readable: "Upper on 42 rows"
  // Per-cell snapshot: Map<filename, {before, after}> for every affected row
  cellSnapshot: Map<string, { before: string; after: string }>;
  // Status snapshot: Map<filename, {before, after}> for validation status changes
  statusSnapshot: Map<string, { before: ValidationOutcome | null; after: ValidationOutcome | null }>;
}
```

**Undo execution:**
1. Iterate `cellSnapshot` — restore each `editedData[field] = before` in Zustand.
2. Iterate `statusSnapshot` — restore each `validation[field].status = before.status`.
3. Fire debounced PATCH for each affected row (or batch — see N+1 pitfall below).
4. Remove entry from undo stack.

**Size concern:** 500 rows × 1 string field = 500 string entries per undo entry. Average ~20 chars/value = ~10KB per entry. 20 undo operations = ~200KB in memory — acceptable. Flag in plan: warn if undo stack exceeds 50 entries (LOW risk for v1 batch sizes).

### Pattern 5: Debounced PATCH for Bulk Transforms

The Phase 9 pattern from `FieldsPane.tsx` uses `useRef<Record<string, ReturnType<typeof setTimeout>>>({})` to debounce per-field. For bulk transforms, Phase 10 needs a different strategy: one PATCH per affected row (not per cell), debounced per `(row_filename + field)` key.

**Critical N+1 avoidance:** A bulk transform touching 500 rows must NOT fire 500 simultaneous PATCH requests. Pattern: collect all row mutations, then fire them with a shared 500ms debounce (one timer per row, coalescing value + validation_status + audit_entry in a single PATCH body).

The `ResultPatch` already accepts `field`, `value`, and `validation_status` in one call. The `audit_entry` field addition (Wave 1) allows the first row's PATCH to carry the full audit entry, and subsequent rows' PATCHes omit it (or repeat it — idempotent append is acceptable since the backend deduplicates by `id` field).

Recommended approach: send `audit_entry` only in the FIRST row's PATCH after the transform. The backend appends it to `checkpoint["audit"]` once.

### Pattern 6: Client-side Validation Re-run after Transform

After a bulk transform, for each affected row, re-run the TS validation port and update Zustand:

```typescript
function revalidateCell(
  fieldName: string,
  newValue: string,
  fieldRules: Record<string, FieldRule> | null,
  currentValidation: ValidationOutcome | null
): ValidationOutcome | null {
  if (!fieldRules?.[fieldName]) return currentValidation; // no rule → leave as-is
  const rule = fieldRules[fieldName];
  const regexOk = rule.pattern ? new RegExp(rule.pattern).test(newValue) : true;
  const vocabOk = rule.vocabulary
    ? rule.vocabulary.some(v => normalizeValue(v) === normalizeValue(newValue))
    : true;
  if (regexOk && vocabOk) return { status: 'valid', rule_failed: null, ... };
  return { status: 'invalid', rule_failed: !regexOk ? 'regex' : 'vocabulary', ... };
}
```

**`verified` status rule:** Only reset `verified` if `newValue !== currentValue`. A no-op transform (e.g., Upper on an already-uppercase value) must NOT mutate status. This check must happen per-cell before any status mutation.

**How to get `fieldRules`:** They live in `config.json` on the batch. The frontend gets them via the batch fetch — but currently `useResultsQuery` only returns results, not config. **Investigation finding:** `batchesApi.ts` has no `fetchBatchConfig` function. Phase 10 needs to either (a) add a `GET /batches/{name}/config` endpoint + `useBatchConfigQuery` hook, or (b) piggyback field_rules onto the existing results response. Option (a) is cleaner. Option (b) would require schema changes. **Recommendation for planner:** Add a minimal `GET /batches/{name}/config` endpoint returning `{field_rules: ..., fields: [...]}` — single-file backend change, read-only, no migration needed. The frontend hook reads it on CleanStep mount.

**Confidence:** MEDIUM — fieldRules access path was not already wired in frontend for post-processing use; requires a new endpoint.

### Pattern 7: Multi-entry Row Expansion in Column View

`ResultsTable.tsx` demonstrates the exact pattern for expanding `_entries` virtual rows. For column view, Phase 10 should use the same expansion logic:

```typescript
// From ResultsTable.tsx lines 77-105 — reuse in CleanStep
type DisplayRow = ResultRow & {
  _pageFilename: string;
  _entryLabel: string;
  _isSubRow: boolean;
};
// filename for virtual rows: `${row.filename}__entry_${idx}`
// This matches the updateResultCell key already used in Zustand
```

The `DisplayRow` type and expansion logic should be extracted to a shared utility (e.g., `src/features/results/expandResults.ts`) in Wave 1 to avoid duplication. Phase 9 also uses the same pattern in `FieldsPane.tsx` via `JSON.parse(card.data['_entries'])`.

### Anti-Patterns to Avoid

- **Storing undo stack in Zustand partialize:** Undo entries contain large per-cell snapshots. They must live in local `useState` inside `CleanStep`/`useCleanState`, not in the persistent store.
- **Re-fetching results on every transform:** Use the already-hydrated Zustand `results` array as the source of truth. Do NOT invalidate the TanStack Query cache after each transform (it would trigger a backend round-trip and overwrite Zustand `editedData`).
- **Using `regex.test()` with global flag on loop:** A `RegExp` created with `/g` flag is stateful — `lastIndex` persists between calls. For pattern facet filtering, always create a new `RegExp` or use the non-global form: `new RegExp(pattern).test(value)`.
- **Title Case with `toLocaleLowerCase('de')`:** German-specific locale lowercasing has pitfalls (Turkish I problem). Recommendation: use standard `toLowerCase()` for Title Case word splitting, then capitalize first char with `toUpperCase()`. For small words like "von", "de", "der" — do not capitalize if not first token. Flag that curator is responsible for domain-specific casing.
- **Blocking the UI during fingerprint computation:** Even at O(n) over 500 rows, computing fingerprints for all columns on view entry is synchronous. Do it lazily per column (only when the column is activated), not eagerly on all columns at once.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Toast for export gate | Custom dialog | `sonner` (already installed) | Matches `checkValidationGate` pattern exactly |
| Regex Replace modal | Custom dialog | Plain React modal with `<textarea>` | No library needed; simple two-input form (find + replace) |
| Debounce timers | Custom scheduler | `useRef<Record<string,ReturnType<typeof setTimeout>>>` | Phase 9 pattern already works perfectly |
| Icon set | Custom SVGs | `lucide-react` (already installed) | `Scissors`, `Sparkles`, `AlignLeft`, `Search`, `Undo2`, `EyeOff` all available |
| UUID for audit entries | External library | `crypto.randomUUID()` or `Date.now().toString(36)` | Web platform; no new dep needed |

**Key insight:** This phase needs zero new npm packages. All UI primitives are available in the existing stack. The fingerprint algorithm is pure string operations over Web platform Unicode APIs.

---

## Common Pitfalls

### Pitfall 1: checkpoint.json format migration breaks existing endpoints
**What goes wrong:** `get_batch_results` returns `checkpoint` directly (currently a list). After migration to `{results:[...], audit:[...]}`, it would return the object instead of the array, breaking the frontend's `ExtractionResult[]` type expectation.
**Why it happens:** Four separate endpoint handlers read checkpoint.json independently with no shared helper function.
**How to avoid:** Wave 1 must update ALL four handlers atomically. Extract a `read_checkpoint(path) -> (list, list)` helper that returns `(results_list, audit_list)` and handles both old (flat list) and new (object) formats. All four handlers call this helper.
**Warning signs:** Frontend shows empty results table after migration.

### Pitfall 2: batchesApi.ts local TS type copies drift
**What goes wrong:** `batchesApi.ts` has manually-maintained local copies of `FieldRule` and `ValidationOutcome` interfaces (lines 6-19). If the `ResultPatch` schema grows an `audit_entry` field, the frontend must also have a matching type for the PATCH call.
**Why it happens:** Schema is defined in `packages/shared-types/schemas/batch.schema.json`, codegen produces `packages/shared-types/generated/ts/index.ts`, but `batchesApi.ts` imports from neither — it maintains its own copies.
**How to avoid:** Wave 1 plan must explicitly add `audit_entry?: AuditEntry | null` to the inline PATCH payload type in `batchesApi.ts` (or add a `patchResult` function there). Do NOT forget to update `templatesApi.ts` if it also has FieldRule copies (verified: it does, at similar location).
**Warning signs:** TypeScript `--noEmit` passes but runtime 422 errors from FastAPI when `audit_entry` is sent.

### Pitfall 3: Python casefold vs JavaScript toLowerCase divergence on ß
**What goes wrong:** Python `"STRASSE".casefold()` → `"strasse"`. JavaScript `"STRASSE".toLowerCase()` → `"strasse"` (same). But `"Straße".casefold()` → `"strasse"` while `"Straße".toLowerCase()` → `"straße"`. The ß → ss expansion only happens in Python casefold.
**Why it happens:** JavaScript `toLowerCase` does not expand ß to ss — this is intentional per Unicode spec; casefold is a separate operation.
**How to avoid:** In `normalizeValue()` TS port, add `v = v.replace(/ß/g, 'ss')` before `toLowerCase()`, matching Python casefold behavior for German text.
**Warning signs:** Cluster picker groups "STRASSE" with "Strasse" but not "Straße" — the most common German archival case.

### Pitfall 4: N+1 PATCH calls from bulk transforms
**What goes wrong:** A bulk transform on 500 rows fires 500 PATCH requests in rapid succession, flooding the FastAPI server (single-threaded) and saturating the browser's HTTP connection pool.
**Why it happens:** Each row needs its own PATCH (different filename). A naive implementation fires one per cell immediately.
**How to avoid:** Per-row debounce timers (500ms, same as Phase 9). Additionally, batch the PATCH for the `audit_entry` — send it only on the FIRST row's PATCH or as a separate `POST /batches/{name}/audit` endpoint. The combined validation-status + value update in a single PATCH body prevents a separate "status" PATCH following a "value" PATCH.
**Warning signs:** Browser Network tab shows hundreds of in-flight PATCH requests.

### Pitfall 5: Pattern facet crashes on malformed regex
**What goes wrong:** User types an incomplete regex like `[abc` — `new RegExp('[abc')` throws a `SyntaxError`, crashing the filter computation.
**Why it happens:** Regex construction is not wrapped in try/catch.
**How to avoid:** All regex operations in pattern facet and Regex Replace must use:
```typescript
try {
  const re = new RegExp(pattern, 'u');
  return re.test(value);
} catch {
  return false; // treat as "no match" for invalid regex
}
```
Also: show a visible error indicator in the PatternFacet input when regex is invalid (red border, "Invalid regex" label). This is a UX requirement for safety.

### Pitfall 6: Sidebar 'clean' step missing from getStepStatus stepOrder
**What goes wrong:** The `getStepStatus` function in `Sidebar.tsx` uses a local `stepOrder` array. If 'clean' is added to the WizardStep union but not to this array, `stepOrder.indexOf('clean')` returns -1, making the clean step always show as 'pending' and the step before it never showing as 'complete'.
**Why it happens:** The stepOrder array is a local constant inside the function, separate from the WizardStep type. Phase 9 hit this exact issue.
**How to avoid:** Search for ALL occurrences of `'verify'` in the codebase and add a parallel `'clean'` entry wherever found. In Wave 1 plan, explicitly list the four insertion points (WizardStep union, STEPS array, stepOrder array, handleStepClick guard, isClickable condition).

### Pitfall 7: Verified-status-survives-no-op requirement
**What goes wrong:** A bulk "Upper" transform is applied to a column. One cell already contains "BERLIN" (already uppercase). The transform correctly leaves the value unchanged, but naive code still drops the `verified` status to `valid`.
**Why it happens:** The code checks "was this transform applied to this row?" rather than "did the value actually change?"
**How to avoid:** Per-cell before-after comparison:
```typescript
if (newValue === currentValue) {
  // No change — preserve all statuses, skip PATCH for this row
  continue;
}
// Only here: update editedData, rerun validation, update status
```
This check must happen BEFORE any Zustand mutation, before any PATCH, and before any undo snapshot entry for that cell.

### Pitfall 8: Audit log size growth
**What goes wrong:** 100 bulk transforms × 500 rows × one audit_entry appended per PATCH = 500 entries in `checkpoint["audit"]` per transform — growing to potentially 50,000 entries for a heavy curation session.
**Why it happens:** The current design sends one audit_entry per row PATCH. Each entry is a small JSON object but the array can grow large.
**How to avoid:** Send the audit_entry only ONCE per operation (not per affected row). Recommendation: add a dedicated `POST /batches/{name}/audit` endpoint, OR send `audit_entry` only in the final (or first) row's PATCH. On the backend, append exactly one audit_entry per operation. The audit_entry contains `affected: N` to capture the row count — no need to itemize per row.
**Warning signs:** `checkpoint.json` grows beyond 1MB for a single batch session.

---

## Code Examples

Verified patterns from existing codebase:

### Phase 9 debounced PATCH pattern (FieldsPane.tsx lines 63-76)
```typescript
// Source: apps/frontend/src/features/verify/FieldsPane.tsx
const patchTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

const handleCommit = useCallback((field: string, newVal: string) => {
  updateResultCell(effectiveFilename, field, newVal);
  // Flip validation status in Zustand...
  clearTimeout(patchTimers.current[field]);
  patchTimers.current[field] = setTimeout(async () => {
    try {
      await axios.patch(
        `/api/v1/batches/${batchId}/results/${encodeURIComponent(card.filename)}`,
        { field, value: newVal, validation_status: 'verified' }
      );
    } catch (err) {
      console.warn('[VerifyStep] PATCH failed for', field, err);
    }
  }, 300);
}, [...]);
```
Phase 10 uses the same pattern with `audit_entry` added to the PATCH body.

### checkValidationGate (useResultsExport.ts lines 38-54) — reuse unchanged
```typescript
// Source: apps/frontend/src/features/results/useResultsExport.ts
function checkValidationGate(onProceed: () => void): void {
  const invalidCount = results.filter((r) =>
    r.validation && Object.values(r.validation).some((v) => v.status === 'invalid')
  ).length;
  if (invalidCount === 0) { onProceed(); return; }
  toast.warning(`${invalidCount} row${invalidCount === 1 ? '' : 's'} have validation issues.`, {
    description: 'Export will proceed if you confirm.',
    action: { label: 'Export anyway', onClick: onProceed },
    cancel: { label: 'Cancel', onClick: () => {} },
    duration: 10000,
  });
}
```
Phase 10 exports pass through this gate unchanged. The `useResultsExport` hook is passed `results` from Zustand — which already reflects bulk-transform edits via `editedData`.

### Multi-entry expansion (ResultsTable.tsx lines 77-105) — reuse pattern
```typescript
// Source: apps/frontend/src/features/results/ResultsTable.tsx
const displayRows = useMemo<DisplayRow[]>(() => {
  const rows: DisplayRow[] = [];
  for (const row of filteredResults) {
    const entriesJson = row.data['_entries'];
    if (row.status === 'success' && entriesJson) {
      const entries = JSON.parse(entriesJson) as Record<string, string>[];
      entries.forEach((entry, idx) => {
        rows.push({
          ...row,
          filename: `${row.filename}__entry_${idx}`,  // virtual filename
          data: entry,
          editedData: {},
          ...
        });
      });
    } else {
      rows.push({ ...row, _pageFilename: row.filename, ... });
    }
  }
  return rows;
}, [filteredResults]);
```
CleanStep uses the same expansion logic. Recommendation: extract to `src/features/results/expandResults.ts` shared utility in Wave 1.

### Python normalize_value (vocab_rules.py — exact TS port target)
```python
# Source: apps/backend/app/services/validation/vocab_rules.py
def normalize_value(value: str) -> str:
    v = value.strip()
    v = unicodedata.normalize("NFC", v)
    v = v.casefold()
    v = unicodedata.normalize("NFD", v)
    v = "".join(c for c in v if unicodedata.category(c) != "Mn")
    return unicodedata.normalize("NFC", v)
```
TS port uses `/\p{Mn}/gu` regex to strip combining marks (Unicode category Mn = Mark, Nonspacing). The `/u` flag enables Unicode property escapes — required for this to work correctly.

### checkpoint.json read helper (backend — new shared utility for Wave 1)
```python
# New helper in batches.py or a separate checkpoint.py module
def read_checkpoint(checkpoint_path: Path) -> tuple[list, list]:
    """Read checkpoint.json. Returns (results_list, audit_list).
    Handles both legacy flat-array format and new {results,audit} object format.
    Migrates legacy format on first read (writes back wrapped format).
    """
    with open(checkpoint_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        # Legacy format — migrate to object format
        obj = {"results": data, "audit": []}
        with open(checkpoint_path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        return data, []
    return data.get("results", []), data.get("audit", [])
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Flat JSON array checkpoint | Object `{results, audit}` | Wave 1 (Phase 10) | All four checkpoint-reading endpoints need update; migration auto-runs on first access |
| `WizardStep` without 'clean' | Add 'clean' as 6th value | Wave 1 (Phase 10) | Sidebar, App.tsx, stepOrder all need update simultaneously |
| No field_rules access in Clean step | `GET /batches/{name}/config` endpoint | Wave 1 (Phase 10) | Needed for client-side validation re-run after transforms |

---

## Open Questions

1. **GET /batches/{name}/config endpoint vs. passing field_rules through results response**
   - What we know: `useResultsQuery` currently returns only `ExtractionResult[]` with no field_rules. `CleanStep` needs `field_rules` to re-run client-side validation after transforms.
   - What's unclear: Whether to add a new read-only endpoint or piggyback config onto the existing results fetch.
   - Recommendation: Add `GET /batches/{name}/config` returning `{fields: string[], field_rules: Record<string, FieldRule> | null}` — single small endpoint, clean separation, no schema drift.

2. **Audit log hydration on CleanStep entry**
   - What we know: CONTEXT.md marks this as Claude's discretion: "recommend: hydrate on entry so prior-session history is visible."
   - What's unclear: Whether `GET /batches/{name}/results` should return the audit log alongside results, or whether a separate fetch is needed.
   - Recommendation: Extend `GET /batches/{name}/results` response to return `{results: [...], audit: [...]}` when the new format exists; or add `GET /batches/{name}/audit` as a separate endpoint. The former is simpler and keeps the CleanStep hydration to one fetch. **Note:** this means the frontend `fetchResults` function and `ExtractionResult[]` return type in `batchesApi.ts` needs updating to `{results: ExtractionResult[], audit: AuditEntry[]}`. Flag for Wave 1.

3. **German ß casefold divergence — add to fingerprint.ts or document-only?**
   - What we know: Python casefold expands ß→ss; JS toLowerCase does not.
   - What's unclear: Whether archival data actually contains mixed ß/ss spellings.
   - Recommendation: Add `v = v.replace(/ß/g, 'ss')` in `normalizeValue()` TS. Cost: negligible. Benefit: correctness for a common German archival case. Flag in plan as a deliberate divergence-fix.

4. **Confirmation dialog for large transforms (>1000 rows)**
   - What we know: CONTEXT.md marks this as Claude's discretion for the planner.
   - Recommendation: Add a simple `sonner.warning` confirmation (same pattern as export gate) when `affectedRows.length > 100`. Threshold is configurable by the planner. This prevents accidental bulk-overwrites on large batches.

---

## Validation Architecture

`workflow.nyquist_validation` is not set in `.planning/config.json` — the config only has project metadata. Based on this, the Validation Architecture section is skipped per researcher instructions.

---

## Suggested Wave Structure

Based on dependency analysis:

**Wave 1 (sequential foundation — all tasks atomic):**
- `10-01`: Backend + schema foundation
  - Extend `ResultPatch` with `audit_entry?: dict | None`
  - Add `read_checkpoint(path)` helper with migration logic
  - Update all 4 checkpoint-reading endpoints to use helper
  - Add `GET /batches/{name}/config` read-only endpoint
  - Add 'clean' to `WizardStep` union + `stepOrder` + Sidebar STEPS + `handleStepClick` + `isClickable` + `App.tsx` routing
  - Extract shared `expandResults.ts` utility from `ResultsTable.tsx`
  - Publish `fingerprint.ts` (normalizeValue + computeFingerprint + buildClusters)

**Wave 2 (parallel — no inter-dependency):**
- `10-02a`: CleanStep shell + ColumnList sidebar + ColumnWorkspace frame + AuditPanel + entry buttons in ResultsStep and VerifyStep
- `10-02b`: ClusterPicker table + TextFacet + PatternFacet + useCleanState hook (column selection, hidden columns, facet filter state)

**Wave 3 (sequential — depends on Wave 2):**
- `10-03`: TransformBar (7 transforms + Regex Replace modal) + undo stack wiring + client-side validation re-run + audit_entry PATCH integration + export gate hookup + integration polish

---

## Sources

### Primary (HIGH confidence)
- Live codebase direct read — `apps/frontend/src/store/wizardStore.ts` — WizardStep union, ResultRow shape, Zustand patterns
- Live codebase direct read — `apps/frontend/src/components/Sidebar.tsx` — exact insertion points for 'clean' step
- Live codebase direct read — `apps/frontend/src/App.tsx` — AppView routing pattern
- Live codebase direct read — `apps/backend/app/api/api_v1/endpoints/batches.py` — PATCH endpoint shape, ResultPatch model, all checkpoint-reading endpoints
- Live codebase direct read — `apps/backend/app/models/schemas.py` — ResultPatch model, ValidationOutcome
- Live codebase direct read — `apps/backend/app/services/validation/vocab_rules.py` — normalize_value pipeline (exact TS port target)
- Live codebase direct read — `apps/frontend/src/features/verify/FieldsPane.tsx` — debounced PATCH pattern
- Live codebase direct read — `apps/frontend/src/features/results/ResultsTable.tsx` — multi-entry expansion pattern
- Live codebase direct read — `apps/frontend/src/features/results/useResultsExport.ts` — checkValidationGate pattern
- Live codebase direct read — `apps/backend/data/batches/Batch_2026-05-18_06-59_08cceedc/checkpoint.json` — confirmed flat-array format
- Live codebase direct read — `packages/shared-types/generated/ts/index.ts` — current generated TypeScript types

### Secondary (MEDIUM confidence)
- Unicode specification — `/\p{Mn}/gu` for combining mark removal — verified against MDN Web platform documentation behavior
- Python-to-JS casefold divergence on ß — verified against ECMAScript spec (toLowerCase does not expand ß)

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries are existing project dependencies; zero new deps needed
- Architecture: HIGH — all patterns read directly from live code; no speculation
- Pitfalls: HIGH — most pitfalls derived from confirmed Phase 8/9 history in STATE.md plus direct code inspection; ß casefold divergence is MEDIUM (confirmed spec but unconfirmed impact on actual data)

**Research date:** 2026-05-18
**Valid until:** 2026-06-18 (stable codebase; only invalidated if Phase 9 code is modified before Phase 10 executes)
