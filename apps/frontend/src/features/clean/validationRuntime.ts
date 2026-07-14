import type { ValidationOutcome, FieldRule } from '../../api/batchesApi';

/**
 * Normalize a string for vocabulary matching and fingerprint clustering.
 * EXACT port of Python vocab_rules.normalize_value() with ß→ss workaround.
 *
 * Pipeline: trim → NFC → ß→ss (Python casefold workaround) → toLowerCase → NFD → strip combining marks → NFC
 *
 * CRITICAL ß WORKAROUND: Python casefold() expands ß→ss (e.g. "Straße"→"strasse"),
 * but JavaScript toLowerCase() does NOT (ß stays ß). For German archival data this
 * matters: "STRASSE" and "Straße" must cluster together. We apply .replace(/ß/g, 'ss')
 * BEFORE toLowerCase() to match Python's casefold behavior.
 * Reference: vocab_rules.py normalize_value(); Python Unicode casefold spec.
 */
export function normalizeValue(value: string): string {
  if (!value) return '';
  let v = value.trim();
  v = v.normalize('NFC');
  v = v.replace(/ß/g, 'ss');    // DELIBERATE: Python casefold ß→ss workaround — must come before toLowerCase
  v = v.toLowerCase();           // JS toLowerCase ≈ Python casefold for non-ß BMP chars
  v = v.normalize('NFD');
  v = v.replace(/\p{Mn}/gu, ''); // strip combining marks (Unicode property Mn = Mark, Nonspacing)
  return v.normalize('NFC');
}

/**
 * Re-run client-side validation for a single cell after a transform.
 * Mirrors Phase 8 backend validation (regex + vocab) but runs in the browser.
 *
 * VERIFIED PRESERVATION RULE: If newValue === currentValue, preserve currentOutcome unchanged.
 * This prevents stripping 'verified' status on no-op transforms (e.g., Upper on already-uppercase "BERLIN").
 *
 * Returns null if no rule exists for the field (leave status as-is).
 */
export function revalidateCell(
  fieldName: string,
  newValue: string,
  currentValue: string,
  fieldRules: Record<string, FieldRule> | null | undefined,
  currentOutcome: ValidationOutcome | null | undefined
): ValidationOutcome | null {
  // No-op check: if value unchanged, preserve ALL status including 'verified'
  if (newValue === currentValue) return currentOutcome ?? null;

  // No rule for this field — leave validation as-is
  if (!fieldRules?.[fieldName]) return currentOutcome ?? null;

  const rule = fieldRules[fieldName];
  let regexOk = true;
  let vocabOk = true;

  // Regex check
  if (rule.pattern) {
    try {
      regexOk = new RegExp(rule.pattern, 'u').test(newValue);
    } catch {
      regexOk = false; // malformed pattern — treat as fail-safe
    }
  }

  // Vocabulary check (case-insensitive via normalizeValue)
  if (rule.vocabulary && rule.vocabulary.length > 0) {
    const normNew = normalizeValue(newValue);
    vocabOk = rule.vocabulary.some(v => normalizeValue(v) === normNew);
  }

  if (regexOk && vocabOk) {
    return {
      ...(currentOutcome ?? {}),
      status: 'valid',
      rule_failed: null,
    } as ValidationOutcome;
  }

  return {
    ...(currentOutcome ?? {}),
    status: 'invalid',
    rule_failed: !regexOk ? 'regex' : 'vocabulary',
  } as ValidationOutcome;
}
