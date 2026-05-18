import { normalizeValue } from './validationRuntime';
import type { DisplayRow } from '../results/expandResults';

/**
 * Fingerprint algorithm: normalize → strip non-alphanumeric → tokenize → dedupe → sort → join.
 * OpenRefine fingerprint spec: tokens are sorted so "Johann Wolfgang" and "Wolfgang Johann" cluster together.
 *
 * SINGLE SOURCE OF TRUTH: Uses normalizeValue() from validationRuntime to ensure identical
 * normalization to Phase 8 vocab rules — including the ß→ss workaround for German archival data.
 * Do NOT re-implement the normalization pipeline here; import from validationRuntime instead.
 */
export function computeFingerprint(value: string): string {
  if (!value?.trim()) return '';
  const norm = normalizeValue(value);
  // Strip non-alphanumeric, non-space characters (punctuation, special chars)
  const stripped = norm.replace(/[^\p{L}\p{N}\s]/gu, '');
  const tokens = stripped.split(/\s+/).filter(Boolean);
  // Dedupe tokens before sorting (OpenRefine spec)
  const unique = [...new Set(tokens)];
  unique.sort();
  return unique.join(' ');
}

export interface ClusterGroup {
  fingerprint: string;
  values: string[];       // distinct raw values with this fingerprint, sorted by frequency desc
  rowCount: number;       // total rows across all variants
  canonical: string;      // pre-filled suggestion = most frequent variant
}

/**
 * Build fingerprint clusters for a given column.
 * Only returns clusters with 2+ distinct raw values (actual near-duplicates).
 * Single-value fingerprints (one canonical spelling) are not clusters.
 * Sorted by rowCount descending — highest-impact clusters first.
 *
 * Lazy by design: called only when a column is activated in ClusterPicker,
 * not for all columns at once (avoids blocking UI on wide datasets).
 */
export function buildClusters(rows: DisplayRow[], field: string): ClusterGroup[] {
  const fpMap = new Map<string, { values: Map<string, number>; rowCount: number }>();

  for (const row of rows) {
    // Use editedData override first, then original data fallback
    const raw: string = (row.editedData?.[field] ?? row.data?.[field] ?? '') as string;
    if (!raw?.trim()) continue;
    const fp = computeFingerprint(raw);
    if (!fp) continue;

    if (!fpMap.has(fp)) fpMap.set(fp, { values: new Map(), rowCount: 0 });
    const entry = fpMap.get(fp)!;
    entry.values.set(raw, (entry.values.get(raw) ?? 0) + 1);
    entry.rowCount++;
  }

  return [...fpMap.entries()]
    .filter(([, e]) => e.values.size >= 2)   // only actual near-duplicates
    .map(([fp, e]) => {
      const sorted = [...e.values.entries()].sort((a, b) => b[1] - a[1]);
      return {
        fingerprint: fp,
        values: sorted.map(([v]) => v),
        rowCount: e.rowCount,
        canonical: sorted[0][0],  // most frequent raw variant
      };
    })
    .sort((a, b) => b.rowCount - a.rowCount);  // highest impact first
}
