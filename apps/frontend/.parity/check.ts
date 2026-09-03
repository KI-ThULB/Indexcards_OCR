// Executes the REAL exporter's column logic so client/server parity is measured,
// not assumed. Throwaway harness: the frontend has no test runner.
import { childNames } from '../src/features/results/groupValue';
import type { FieldGroup } from '../src/api/batchesApi';

const group: FieldGroup = {
  description: null, max_items: 20,
  fields: [{ name: 'Lfd_Nr' }, { name: 'Titel' }, { name: 'Spieldauer' }],
};

function groupColumns(label: string, g: FieldGroup): string[] {
  const children = childNames(g);
  const columns: string[] = [`${label}_count`];
  for (let i = 1; i <= g.max_items; i++) {
    for (const child of children) {
      const base = `${label}_${i}_${child}`;
      columns.push(`${base}_ocr`, `${base}_edited`, `${base}_confidence`);
    }
  }
  columns.push(`${label}_overflow_json`);
  return columns;
}
console.log(JSON.stringify(groupColumns('Titel_Tracks', group)));
