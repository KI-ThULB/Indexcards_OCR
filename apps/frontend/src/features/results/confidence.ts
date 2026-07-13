// Confidence display helpers (feature: per-field + overall VLM confidence).
// The VLM self-reports confidence 0–1; we surface it as a 0–100% figure with a
// green/amber/red band so a curator can triage which cards/fields need checking.
// These are QA signals, not ground truth — the colour band keeps that honest.

export const CONFIDENCE_HIGH = 0.85; // ≥ → green
export const CONFIDENCE_MID = 0.6;   // ≥ → amber, else red

export type ConfidenceBand = 'high' | 'medium' | 'low';

export function confidenceBand(score: number | null | undefined): ConfidenceBand | null {
  if (score === null || score === undefined || Number.isNaN(score)) return null;
  if (score >= CONFIDENCE_HIGH) return 'high';
  if (score >= CONFIDENCE_MID) return 'medium';
  return 'low';
}

/** Tailwind text/bg classes for a confidence band (parchment-friendly). */
export function confidenceClasses(score: number | null | undefined): string {
  switch (confidenceBand(score)) {
    case 'high':
      return 'text-green-700 bg-green-50/80';
    case 'medium':
      return 'text-amber-700 bg-amber-50/80';
    case 'low':
      return 'text-red-600 bg-red-50/80';
    default:
      return 'text-archive-ink/30';
  }
}

/** Format a 0–1 score as a whole percentage, or '—' when absent. */
export function confidencePct(score: number | null | undefined): string {
  if (score === null || score === undefined || Number.isNaN(score)) return '—';
  return `${Math.round(score * 100)}%`;
}
