export interface ValidationPreset {
  id: string;
  label: string;
  pattern: string;
  description: string;
  hasPrefixInput?: boolean;
}

export const VALIDATION_PRESETS: ValidationPreset[] = [
  { id: 'none',        label: 'No rule',                   pattern: '',                             description: 'No validation' },
  { id: 'required',    label: 'Required / Non-empty',      pattern: '^.+$',                         description: 'Field must not be empty' },
  { id: 'year',        label: 'Year (YYYY)',                pattern: '^\\d{4}$',                     description: 'Four-digit year' },
  { id: 'year_range',  label: 'Year Range (YYYY–YYYY)', pattern: '^\\d{4}[–\\-]\\d{4}$', description: 'Year range with dash or en-dash' },
  { id: 'iso_date',    label: 'ISO Date (YYYY-MM-DD)',      pattern: '^\\d{4}-\\d{2}-\\d{2}$',      description: 'ISO 8601 date' },
  { id: 'german_date', label: 'German Date (DD.MM.YYYY)',   pattern: '^\\d{2}\\.\\d{2}\\.\\d{4}$',  description: 'German date format' },
  { id: 'gnd_id',      label: 'GND Authority ID',           pattern: '^(DE-588)?[0-9X]+$',           description: 'GND identifier' },
  { id: 'rkd_id',      label: 'RKD Authority ID',           pattern: '^\\d+$',                       description: 'RKD numeric identifier' },
  { id: 'aat_id',      label: 'Getty AAT ID',               pattern: '^aat:\\d+$',                   description: 'AAT concept identifier' },
  { id: 'viaf_id',     label: 'VIAF ID',                    pattern: '^\\d+$',                       description: 'VIAF numeric identifier' },
  { id: 'prefix',      label: 'Prefix Pattern',             pattern: '',                             description: 'User-supplied prefix + digits', hasPrefixInput: true },
  { id: 'custom',      label: 'Custom Regex',               pattern: '',                             description: 'User-supplied regex pattern' },
  { id: 'vocabulary',  label: 'Closed Vocabulary',          pattern: '',                             description: 'Match against a list of allowed values' },
];

/** Escape user-supplied prefix and build a regex that requires prefix followed by digits. */
export function buildPrefixPattern(prefix: string): string {
  const esc = prefix.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return `^${esc}\\d+$`;
}
