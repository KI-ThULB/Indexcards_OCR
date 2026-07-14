# Phase 11: Authority Reconciliation - Context

**Gathered:** 2026-05-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Match free-text values in extracted fields against four external **authority files** and emit the resulting URIs into existing LIDO / MARCXML / Dublin Core exports. Authorities in scope:

- **GND** (Gemeinsame Normdatei, German National Library) — with sub-collections: Persons, Places, Subjects, Corporate Bodies, Works
- **Wikidata** — multilingual entities of all kinds
- **GeoNames** — places worldwide
- **Getty AAT** (Art & Architecture Thesaurus) — art/architecture subject terms

Reconciliation is a per-field configuration (Configure step), runs in Clean view (Phase 10) as a new pane/tool, supports per-cell candidate picking AND bulk column mode, and persists results as per-cell URIs alongside Phase 8's ValidationOutcome.

**In scope:** authority binding on MetadataField, candidate picker UI, bulk-column auto-accept, per-batch cache, backend `/api/v1/reconcile` endpoint, URI emission in LIDO + MARCXML + Dublin Core exports.

**Out of scope for v1:** authorities beyond the four named; URI emission in formats other than LIDO/MARC/DC (EAD, Darwin Core, METS/MODS, etc. stay unchanged); aggressive similarity-threshold auto-accept; per-authority TTL; cross-authority cache; export gate based on unreconciled cells; "URI-only" export mode.

</domain>

<decisions>
## Implementation Decisions

### Authority selection & field mapping
- **All four authorities ship in v1:** GND (with sub-collections), Wikidata, GeoNames, Getty AAT.
- **GND sub-collections are separate authority options** in the binding dropdown: `gnd-persons`, `gnd-places`, `gnd-subjects`, `gnd-corporate-bodies`, `gnd-works`. Each maps to the corresponding GND entity-type filter on the search API (e.g., Lobid `filter=type:Person`). Precision-aware: prevents "Berlin (Familienname)" from contaminating Place searches.
- **Authority binding is per-field config** in the Configure step. Each FieldManager row gets an authority dropdown alongside the Phase 8 validation-rule editor. Stored on the MetadataField:
  ```ts
  type AuthorityType = 'gnd-persons' | 'gnd-places' | 'gnd-subjects' | 'gnd-corporate-bodies' | 'gnd-works' | 'wikidata' | 'geonames' | 'aat' | null
  type AuthorityBinding = { type: AuthorityType }
  type MetadataField = { /* existing */ ..., rule?: FieldRule | null, authority?: AuthorityBinding | null }
  ```
- **Persistence mirrors the Phase 8 `field_rules` pattern exactly:** Zustand state, round-tripped through template save/load, snapshotted into batch `config.json` on batch creation. Re-reconciliation uses the same snapshot — bindings can't drift after batch start.

### Workflow placement & per-cell vs bulk modes
- **Lives inside Clean view (Phase 10).** No new wizard step. "Reconcile column" surfaces as a button alongside the TransformBar (or as its own tab inside ColumnWorkspace — Claude's discretion on exact placement). Per-cell reconciliation also triggerable from Results table (inline icon, Claude's discretion on exact icon placement).
- **Candidate picker = inline drawer** below the cell. Shows top 5 candidates, each row: bold label, gray description, small URI link, "Pick this" button. "No match" button to escape. "Search again with different query" input lets the curator refine the query without leaving the drawer. Familiar OpenRefine pattern; doesn't take the curator out of the column workspace.
- **Bulk column mode = auto-accept exact-match-single-candidate + queue rest for review:**
  - For each cell in the column, query the bound authority with the cell value.
  - If the API returns **exactly ONE candidate** AND `normalizeValue(candidate.label) === normalizeValue(cellValue)` (using the same NFC + ß→ss + casefold + strip-marks pipeline from Phase 8/10), **auto-accept** and write reconciliation. Audit entry records `source: 'reconciliation-auto'`.
  - Otherwise, cell goes into a "Needs review" queue. Curator opens each queued cell and uses the inline drawer (or "No match"). Audit source: `'reconciliation-manual'`.
  - No similarity-threshold tuning. Predictable rule.
- **Reconciliation status = new optional field on ValidationOutcome (sibling to status):**
  ```ts
  type ReconciliationOutcome = {
    authority: AuthorityType
    uri: string
    label: string
    picked_by: 'auto' | 'manual'
    picked_at: string  // ISO date
  }
  type ValidationOutcome = { /* existing */ status, rule_failed?, vlm_value?, corrector_proposal?, corrector_rationale?, reconciliation?: ReconciliationOutcome | null }
  ```
  Independent dimension from `status`. A cell can be `verified` AND reconciled; or `invalid` and reconciled; or any combination. The verified flag is about value-correctness; reconciliation is about URI-identity.
- **Editing a reconciled cell drops the reconciliation** (any actual value change clears `validation.reconciliation`). Mirrors Phase 9's "verified survives only no-op edits". Curator must re-reconcile the new value. No-op edits leave it intact. Audit logs the drop.

### Caching & external-API governance
- **Cache lives server-side, per-batch:** new file `data/batches/{batch_name}/authority_cache.json`. Shape:
  ```json
  { "<authority>:<normalized_query>": [{ "label": "...", "uri": "...", "description": "..." }, ...] }
  ```
  Keyed by authority+normalizedQuery (same NFC + ß→ss + casefold + strip-marks normalization the rest of the app uses — single source of truth). Sibling to checkpoint.json; bounded by batch lifetime; exportable as part of batch data.
- **No TTL.** Cache forever. Per-batch "Clear cache" button in the Reconcile pane handles the rare case the curator believes an authority has changed. Authority files are stable enough that automatic expiry costs more than it saves.
- **Backend exponential-backoff retry:** 3 attempts at 1s / 2s / 4s for 429 / 5xx / network errors. After 3 failures, cell shows an "API error — retry?" affordance in the drawer (not silently dropped). Bulk-mode treats persistent failures as "needs review" so the curator can re-trigger after rate limits clear.
- **Authority-specific rate caps respected:** Wikidata ~50 req/s anonymous, GeoNames 2000/hr free tier with named account, GND/AAT looser. Backend implementation orchestrates the throttling — bulk-mode serializes per authority.
- **All authority API calls go through one backend endpoint:** `POST /api/v1/reconcile` with body `{ authority: AuthorityType, query: string }` returns `{ candidates: [{label, uri, description}, ...] }`. Cache lookup, retry logic, secrets (GeoNames username, etc.), throttling all live server-side. Frontend has one URL regardless of authority.

### Authority URI emission in exports
- **Three exports get URIs in v1:** LIDO, MARCXML, Dublin Core. The other Phase 6 exports (EAD, Darwin Core, METS/MODS) stay unchanged (their authority-URI slots are either nonstandard or absent).
- **LIDO:** authority URIs go into the standard slots — `<lido:conceptID lido:type="URI" lido:source="GND">http://d-nb.info/gnd/118540238</lido:conceptID>` for terms; analogous URI fields for actors (`<lido:actorID>`).
- **MARCXML:** authority URIs go into subfield `$0` per MARC21 convention. E.g., `<marc:subfield code="0">(DE-588)118540238</marc:subfield>` for GND, `<marc:subfield code="0">http://www.wikidata.org/entity/Q5879</marc:subfield>` for Wikidata.
- **Dublin Core:** authority URIs emitted as `<dcterms:identifier>http://d-nb.info/gnd/118540238</dcterms:identifier>` alongside the human-readable value.
- **Unmatched cells (no URI):** emit the raw value only, omit the URI attribute/subfield/identifier. Field still appears in XML; URI slot absent. Standard consumer behavior: treat URI-less entries as unauthoritative.
- **Export gate (Phase 8 soft-block) stays unchanged.** Only `status: invalid` triggers the soft-block. Unreconciled cells do NOT block exports — reconciliation is optional metadata enrichment, not a quality requirement.

### Claude's Discretion
- Exact placement of "Reconcile" button in Clean view (TransformBar adjacent vs own tab vs ColumnWorkspace section)
- Exact inline-drawer dimensions, candidate-row styling, "Search again" affordance positioning
- Whether the candidate-picker drawer also surfaces in Results table or stays Clean-only (recommend: Clean for bulk, plus a per-cell icon in Results for one-off picks — Claude's call)
- Default authority value in the Configure dropdown when a new field is added (`null` is safe; field-name heuristic could be offered as a "suggested" hint that the curator confirms)
- Wikidata language preference for candidate labels (recommend: German first, English fallback — Claude's call)
- Visual badge for reconciled cells in Results/Verify/Clean (likely a small link icon + tooltip showing the URI; consistent with ValidationBadge styling)
- Exact JSON shape of the cache file beyond the key→candidates mapping (LRU eviction not needed per-batch)
- How "No match" is recorded — likely `validation.reconciliation = null` with an audit entry saying source='reconciliation-no-match', so the cell isn't re-queried on subsequent bulk runs
- Whether the cache stores "no candidates found" results too (recommend: yes, with shape `{ "<authority>:<query>": [] }` so cache hits include empty results)
- Whether the GeoNames username comes from env (recommend: yes, `GEONAMES_USERNAME` env var, parallel to `OPENROUTER_API_KEY`); error UX if missing
- Audit panel rendering of reconciliation entries — likely a "🔗 reconciled to gnd:..." line with click-to-open URI

</decisions>

<specifics>
## Specific Ideas

- **OpenRefine reconciliation** is the canonical UX precedent — curators in digital humanities already know it. Match the candidate-picker + bulk-auto-accept-on-single-exact patterns from there.
- **Lobid** (https://lobid.org/gnd) is the recommended GND API wrapper (faster than DNB SRU for short queries, JSON-LD response). Wikidata uses `wbsearchentities`. GeoNames `search` JSON endpoint. Getty AAT exposes a SPARQL endpoint and a Reconciliation-API-protocol endpoint — the latter is closer to what OpenRefine implements and likely cleaner for our use case.
- **Wikidata QIDs (`http://www.wikidata.org/entity/Q5879`)** and **GND URIs (`http://d-nb.info/gnd/118540238`)** are the canonical forms expected by LIDO/MARC consumers.
- The `(DE-588)` MARC subfield prefix is the MARC convention for GND IDs (DE-588 = ISIL of Deutsche Nationalbibliothek). MARC consumers expect it; don't use the URI form in the subfield.
- The Phase 8 `normalizeValue` (NFC + ß→ss + casefold + strip-marks) is **the right normalization** for the bulk-mode exact-match check too. Same TS utility from `validationRuntime.ts`. Don't reinvent.
- The Phase 10 audit log handles reconciliation actions naturally — `source: 'reconciliation-auto' | 'reconciliation-manual' | 'reconciliation-cleared-by-edit' | 'reconciliation-no-match'`. Existing AuditEntry shape extends without schema change.

</specifics>

<deferred>
## Deferred Ideas

- **Additional authorities** — LCNAF (Library of Congress Name Authority File), ULAN (Getty Union List of Artist Names), VIAF aggregator, ISNI, ORCID for living people. Each is its own integration; v1 covers the four that LIDO/MARC/DC most expect for German archival data.
- **Configurable similarity-threshold auto-accept** — slider in bulk-mode UI for "auto-accept if best candidate similarity ≥ X". v1 sticks to "exact normalized match + single candidate". Defer.
- **Per-authority TTL** — fine-grained cache lifetime per authority. v1 has no TTL. Defer.
- **Global authority cache** — shared across batches. v1 cache is per-batch. Defer.
- **Soft-block export on unreconciled cells in authority-bound columns** — stricter gate. v1 keeps Phase 8's gate unchanged. Could be added as an opt-in setting later.
- **URI emission in EAD / Darwin Core / METS/MODS / other Phase 6 exports** — these formats either don't have well-defined authority-URI slots or use them differently. Defer; researcher can investigate which formats might fit naturally in a follow-up phase.
- **"Export only fully-reconciled rows" mode** — adds export-flow complexity. v1 exports all rows; URI-less cells stay URI-less in the output.
- **Authority-side write-back** — emitting batch data BACK to authority files (e.g., proposing new GND entries for unmatched cells). Way out of scope.
- **Reconciliation across multiple authorities per field** — bind one field to GND-Persons AND Wikidata, prefer GND but fall back. Adds complex precedence rules. Defer.

</deferred>

---

*Phase: 11-authority-reconciliation*
*Context gathered: 2026-05-18*
