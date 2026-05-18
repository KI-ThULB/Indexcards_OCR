import React, { useMemo } from 'react';
import type { DisplayRow } from '../results/expandResults';

interface TextFacetProps {
  displayRows: DisplayRow[];
  field: string;
  selectedValues: Set<string>;              // current active filter selection
  onSelectionChange: (values: Set<string>) => void;
}

/**
 * Shows all unique non-empty values for the active column with counts.
 * Click to toggle multi-select filter. Faceted rows are the transform scope.
 * Values sorted by frequency descending (most common first).
 */
export function TextFacet({ displayRows, field, selectedValues, onSelectionChange }: TextFacetProps) {
  const valueCounts = useMemo(() => {
    const map = new Map<string, number>();
    for (const row of displayRows) {
      const v = (row.editedData?.[field] ?? row.data?.[field] ?? '') as string;
      if (v?.trim()) map.set(v, (map.get(v) ?? 0) + 1);
    }
    return map;
  }, [displayRows, field]);

  const sortedValues = useMemo(() =>
    [...valueCounts.entries()].sort((a, b) => b[1] - a[1]),
    [valueCounts]
  );

  if (sortedValues.length === 0) {
    return (
      <p className="text-sm text-archive-400 text-center py-4">No values in this column.</p>
    );
  }

  return (
    <div>
      {/* Header row with count and clear button */}
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-archive-100">
        <span className="text-xs text-archive-500">{sortedValues.length} unique value{sortedValues.length !== 1 ? 's' : ''}</span>
        {selectedValues.size > 0 && (
          <button
            onClick={() => onSelectionChange(new Set())}
            className="text-xs text-archive-600 hover:underline"
          >
            Clear filter
          </button>
        )}
      </div>

      {/* Value list — scrollable */}
      <div className="overflow-y-auto max-h-48">
        {sortedValues.map(([value, count]) => (
          <div
            key={value}
            onClick={() => {
              const next = new Set(selectedValues);
              if (next.has(value)) { next.delete(value); } else { next.add(value); }
              onSelectionChange(next);
            }}
            className={`flex items-center gap-2 px-3 py-1.5 cursor-pointer text-sm transition-colors
              ${selectedValues.has(value)
                ? 'bg-archive-100 text-archive-900 font-medium'
                : 'text-archive-700 hover:bg-archive-50'
              }
            `}
          >
            <span className="flex-1 truncate">
              {value || <em className="text-archive-400">empty</em>}
            </span>
            <span className="text-xs text-archive-400 tabular-nums">{count}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
