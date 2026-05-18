import type { ResultRow } from '../../store/wizardStore';

export type DisplayRow = ResultRow & {
  _pageFilename: string;   // always the original page filename (for PATCH calls)
  _entryLabel: string;     // 'Entry 1', 'Entry 2', etc., or '' for single-entry rows
  _isSubRow: boolean;      // true for entries 2+ of a multi-entry card
};

/**
 * Expand ResultRow[] into DisplayRow[] by flattening multi-entry cards.
 * Multi-entry cards (with data['_entries']) produce one DisplayRow per entry.
 * Virtual filenames for sub-rows: `${row.filename}__entry_${idx}` — matches updateResultCell key.
 * Single-entry rows produce one DisplayRow with _isSubRow=false.
 */
export function expandResults(rows: ResultRow[]): DisplayRow[] {
  const result: DisplayRow[] = [];
  for (const row of rows) {
    const entriesJson = row.data['_entries'];
    if (row.status === 'success' && entriesJson) {
      try {
        const entries = JSON.parse(entriesJson as string) as Record<string, string>[];
        if (entries.length === 0) {
          result.push({
            ...row,
            data: { '_entries': '[]', 'Hinweis': 'Keine Einträge erkannt' },
            _pageFilename: row.filename,
            _entryLabel: '0 Einträge',
            _isSubRow: false,
          });
        } else {
          const total = entries.length;
          entries.forEach((entry, idx) => {
            result.push({
              ...row,
              filename: `${row.filename}__entry_${idx}`,
              data: entry,
              editedData: {},
              _pageFilename: row.filename,
              _entryLabel: `${idx + 1} / ${total}`,
              _isSubRow: idx > 0,
            });
          });
        }
      } catch {
        result.push({ ...row, _pageFilename: row.filename, _entryLabel: '', _isSubRow: false });
      }
    } else {
      result.push({
        ...row,
        _pageFilename: row.filename,
        _entryLabel: '',
        _isSubRow: false,
      });
    }
  }
  return result;
}
