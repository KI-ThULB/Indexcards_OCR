import React, { useMemo } from 'react';
import { Eye, EyeOff } from 'lucide-react';
import type { DisplayRow } from '../results/expandResults';

interface ColumnListProps {
  columns: string[];                           // field names, excluding _-prefixed internal fields
  activeColumn: string | null;
  hiddenColumns: Set<string>;
  onSelectColumn: (col: string) => void;
  onToggleHide: (col: string) => void;
  displayRows: DisplayRow[];                   // expanded rows for count computation
}

export const ColumnList: React.FC<ColumnListProps> = ({
  columns,
  activeColumn,
  hiddenColumns,
  onSelectColumn,
  onToggleHide,
  displayRows,
}) => {
  // Compute per-column stats: rowCount and uniqueCount
  const columnStats = useMemo(() => {
    const stats = new Map<string, { rowCount: number; uniqueCount: number }>();
    for (const col of columns) {
      const values: string[] = [];
      for (const r of displayRows) {
        const val = r.editedData?.[col] ?? r.data?.[col] ?? '';
        if (val && val !== '') {
          values.push(val as string);
        }
      }
      const rowCount = values.length;
      const uniqueCount = new Set(values).size;
      stats.set(col, { rowCount, uniqueCount });
    }
    return stats;
  }, [columns, displayRows]);

  return (
    <div className="w-48 flex-shrink-0 border-r border-archive-200 overflow-y-auto bg-parchment-50 flex flex-col">
      {/* Header */}
      <div className="text-xs font-semibold uppercase tracking-wide text-archive-500 px-3 py-2 border-b border-archive-100 shrink-0">
        Columns
      </div>

      {/* Column rows */}
      <div className="flex-1 overflow-y-auto">
        {columns.length === 0 && (
          <p className="px-3 py-4 text-xs text-archive-400 italic">No fields available.</p>
        )}
        {columns.map((col) => {
          const isActive = col === activeColumn;
          const isHidden = hiddenColumns.has(col);
          const stats = columnStats.get(col) ?? { rowCount: 0, uniqueCount: 0 };

          return (
            <div
              key={col}
              onClick={() => !isHidden && onSelectColumn(col)}
              className={`group flex items-center gap-2 px-3 py-2 cursor-pointer rounded-md text-sm transition-colors
                ${isActive ? 'bg-archive-100 text-archive-900 font-medium' : 'text-archive-700 hover:bg-archive-50'}
                ${isHidden ? 'opacity-40 cursor-default' : ''}
              `}
            >
              <span className="flex-1 truncate">{col}</span>
              <span className="text-xs text-archive-400 tabular-nums shrink-0">
                {stats.uniqueCount}u / {stats.rowCount}r
              </span>
              <button
                onClick={(e) => { e.stopPropagation(); onToggleHide(col); }}
                className="opacity-0 group-hover:opacity-100 transition-opacity p-0.5 rounded hover:text-archive-600 shrink-0"
                title={isHidden ? 'Show column' : 'Hide column'}
              >
                {isHidden ? <Eye size={14} /> : <EyeOff size={14} />}
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
};
