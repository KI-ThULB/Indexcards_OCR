# Phase 10: OpenRefine-style Cleaning Stage - Context

**Gathered:** 2026-05-18
**Status:** Ready for planning

<domain>
## Phase Boundary

A column-wise data-quality workspace operating over batch results. Curator works on one **column** (one extracted field across all cards) at a time, not one card at a time. Core capabilities for v1:

- **Fingerprint clustering** — group near-duplicate values (e.g., "Goethe", "GOETHE ", "goethe") into one cluster, propose a canonical value, apply across selected rows
- **Faceting** — filter the active column to rows matching a value (text facet) or pattern (regex pattern facet)
- **Bulk transforms** — apply Trim, Upper, Lower, Title Case, Collapse-whitespace, Regex Replace, Set-to-NULL across the currently faceted rows of a column
- **Undo/audit** — per-operation undo stack within session, audit log persists to `checkpoint.json` for permanent provenance

Sits as the 6th wizard step (Upload → Configure → Processing → Results → Verify → Clean) and consumes/produces the same ResultRow shape as Phase 9. Edits flow through the same `PATCH /api/v1/batches/{batch_name}/results/{filename}` endpoint added in Phase 9.

**Out of scope for v1:** n-gram and Levenshtein clustering algorithms (fingerprint only), GREL/custom expression language, numeric/date/scatter facets (text + pattern only), cross-session undo, multi-column transforms.

</domain>

<decisions>
## Implementation Decisions

### Workflow placement & scope
- Clean is the **6th wizard step**, optional, opt-in. Order: Upload → Configure → Processing → Results → Verify → Clean.
- **Entry points:** "Clean columns" buttons on **both** Results and Verify steps (mirrors Phase 9's "Verify cards" placement). Curators coming from either direction can jump to Clean without backtracking.
- **Layout:** **column-list sidebar + main column workspace**. Left sidebar lists all extracted fields with per-field row count and unique-value count; clicking a field activates it in the main pane (cluster suggestions + facet filters + transform tools + audit log).
- **Column scope:** all extracted fields are cleanable by default; each row in the sidebar has a hide affordance (hidden columns remain in the data, just not in the cleaning UI).
- **Edit overlap with Verify:** both write to the same `editedData` map through the same PATCH endpoint. The audit log records the **source** of each change (`vlm-original`, `cockpit-edit`, `bulk-transform`, `cluster-merge`) as provenance. Last write wins.
- **Multi-entry rows** (Findmittel `_entries`): **each entry is its own row** in column view. A 3-entry card contributes 3 rows; bulk transforms apply per-row.
- **Audit log UX:** **collapsible side/bottom panel**, persistent across column switches, most recent on top, per-entry Undo button. Always visible (collapsible when cramped). Mirrors OpenRefine's history panel.
- **Auto-actions:** none. Nothing runs automatically on view entry or column open. Every operation requires explicit curator action — safer and predictable; mirrors OpenRefine.

### Clustering & faceting mechanics
- **Algorithm:** **fingerprint only** for v1 (Unicode-aware: NFKD/NFC + casefold + strip-punct + strip-diacritics + sort tokens + join). Algorithm of last resort; covers >80% of real-world duplicate cases. n-gram and Levenshtein deferred.
- **Compute location:** **frontend, client-side** over already-hydrated `results` from `useResultsQuery`. Fingerprint is O(n) string ops; sub-100ms on 500+ rows. No new clustering endpoint, no network round-trips on threshold changes.
- **Cluster picker UI:** **table** — one row per cluster, columns: cluster id / variant values (comma-joined) / row count / suggested canonical value (editable text input, pre-filled with most common variant) / Apply / Skip. Matches OpenRefine's cluster dialog.
- **Faceting:** **text facet** (unique-values list with counts, click-to-filter, multi-select) **AND pattern facet** (filter rows whose value matches a regex). Numeric/date/scatter facets deferred.

### Bulk transforms & undo/commit
- **v1 transforms (7):** Trim, Upper, Lower, Title Case, Collapse-whitespace, Regex Replace (modal with find / replace inputs supporting capture groups), Set-to-NULL.
- **Row scope:** the **currently faceted rows in the active column**. If no facet active, the entire column. "I see what I'm about to change" — matches OpenRefine semantics exactly. Audit log records the affected count: "Trimmed 142 of 500 rows".
- **Undo:** **per-operation stack, unlimited within session**, in-memory. Every transform, cluster merge, or cell edit pushes an entry; clicking Undo on any audit entry reverts that operation. Stack evaporates on reload (cross-session undo deferred).
- **Persistence:** **autosave via debounced PATCH (~500ms)** through the existing `PATCH /results/{filename}` endpoint (Phase 9). No explicit Save button. Crash-resilient.
- **Audit log lifetime:** **persisted server-side in `checkpoint.json`** alongside results. PATCH endpoint accepts an `audit_entry` field that gets appended server-side. Permanent provenance; surviving curator: "I see GOETHE in this cell now, but the audit shows it was 'Goethe ' from the VLM and got Upper-cased on 2026-05-18".

### Status integration with Phase 8/9
- **Validation status on bulk transform:** **re-run client-side validation on the new value**. The cell's `field_rules` are already snapshotted on the batch (Phase 8 stored them in `config.json`, frontend has them via batch fetch). Status flips to `valid` if it now passes, stays `invalid` if not. Keeps validation badges meaningful after cleaning.
- **`verified` status preservation:** **keep `verified` only if the value didn't change** (e.g., Upper on already-uppercase string). Any actual value change drops `verified` and falls back to the new validation outcome (`valid` / `invalid` / `corrected`). A verification claim is about a specific string, not a moving target.
- **Validation runtime:** **TypeScript port of the Phase 8 regex + vocab rules** shipped client-side. The Python `regex_rules.py` and `vocab_rules.py` are simple enough to mirror in TS (regex test, NFC + casefold + strip-marks normalization, exact + fuzzy match via a JS Levenshtein/rapidfuzz-equivalent). Zero new backend endpoints, instant live-status feedback after each transform.
- **Export gate:** **reuse the existing Phase 8 soft-block gate unchanged**. Same `checkValidationGate` that all 8 Results exports use; an export from Clean view triggers the same sonner "N rows invalid — export anyway?" confirmation. Single source of truth for "is this batch export-ready".

### Claude's Discretion
- Exact sidebar dimensions, sidebar layout (text size, count badges), and column-row hover affordances
- Position and width of the audit-log panel (side vs bottom), collapse animation, max visible entries before scrolling
- Default sort order in the cluster picker table (likely by affected row count, descending)
- Canonical-value heuristic in the cluster picker (most common variant; could be smarter — Claude can choose)
- Regex flavor for both Regex Replace and pattern facet (JS regex is implied — document if anything else)
- Title Case rules (locale-aware? articles like "von" / "the" handled?) — Claude can settle during planning
- Audit log entry shape (timestamp / op / details — but should include enough to render and undo the operation)
- Empty-state copy when no clusters/facets/transforms have run yet
- Exact debounce ms (500ms baseline acceptable; tune if needed)
- Whether the audit log panel re-loads its contents from `checkpoint.json` on view entry or only persists outgoing entries (recommend: hydrate on entry so prior-session history is visible — but Claude can decide)
- Confirmation prompt for destructive transforms over very large row counts (e.g., >1000 rows): Claude can decide whether to add a soft confirm

</decisions>

<specifics>
## Specific Ideas

- The reference tool is **OpenRefine** (Google/Metaweb, then community-maintained). The cluster dialog, history panel, text-facet behavior, and per-column transform dropdowns are well-known to digital-humanities curators — match those affordances where reasonable.
- The cleaning workflow is meant for **archival quality work** — the same audiences who would re-cluster proper-noun spellings and normalize date formats before exporting to LIDO/MARC. Provenance matters: that's why the audit log is persisted server-side instead of in-memory.
- The Phase 8 `vocab_rules` Unicode normalization (NFC + casefold + strip-combining-marks) is **the right normalization** for fingerprint clustering too — the TS port should produce identical fingerprints to a backend-computed reference. This is the spec, not coincidence.
- The Verify cockpit's `verified` semantics are intentionally **fragile under transforms**: human verification is about a specific value. Once Clean rewrites that value, the human verification claim is dead. Restoring the prior status (or the new validation outcome) keeps the badge truthful.

</specifics>

<deferred>
## Deferred Ideas

- **n-gram fingerprint, Levenshtein-similarity, phonetic clustering** — additional cluster algorithms with their own UI (threshold sliders, algorithm switcher). Defer to a follow-up cleaning-stage iteration once curators report what fingerprint misses.
- **GREL-like expression language** for custom transforms. Out of scope; a separate phase if/when needed.
- **Numeric / date / scatter facets** — type inference required; out of scope for v1.
- **Cross-session undo** — undo stack persisted server-side allowing reverts days later. Adds significant state-machine complexity around multi-session conflicts; deferred until there's evidence of demand.
- **Cross-column transforms** — derive one column's value from another, batch-apply (e.g., "fill blank Birthplace from non-blank Origin"). Out of scope for v1.
- **Confirmation prompt for very large operations** — a soft-confirm when a transform would touch >N rows. Claude has discretion to add this during planning; flagged as a possible polish item.
- **Audit log export** — exporting the cleaning history as a separate artifact for institutional records. The log will be in `checkpoint.json` (so technically queryable), but a dedicated export UI is out of scope for v1.

</deferred>

---

*Phase: 10-openrefine-style-cleaning-stage*
*Context gathered: 2026-05-18*
