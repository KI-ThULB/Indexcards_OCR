import React, { useState, useRef, useEffect, useMemo } from 'react';
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  createColumnHelper,
  type SortingState,
} from '@tanstack/react-table';
import { RotateCcw, Loader2 } from 'lucide-react';
import Lightbox from 'yet-another-react-lightbox';
import 'yet-another-react-lightbox/styles.css';
import { useWizardStore, type ResultRow } from '../../store/wizardStore';
import { ThumbnailCell } from './ThumbnailCell';
import { ValidationBadge } from './ValidationBadge';
import type { ValidationFilter } from './ValidationFilterChips';

interface ResultsTableProps {
  results: ResultRow[];
  fields: string[];
  batchName: string;
  onRetryImage: (filename: string) => void;
  isProcessing: boolean;
  retryingFilename?: string | null;
  validationFilter?: ValidationFilter;
}

// DisplayRow extends ResultRow with multi-entry metadata for Findmittel pages
type DisplayRow = ResultRow & {
  _pageFilename: string;  // Original source page filename
  _entryLabel: string;    // e.g. "2 / 7" (entry number / total entries)
  _isSubRow: boolean;     // true = sub-row from a multi-entry Findmittel array
};

const statusStyles = {
  success: 'text-green-700 bg-green-50/80',
  failed:  'text-red-600  bg-red-50/80',
} as const;

const rowBg = {
  success: '',
  failed:  'bg-red-50/10',
} as const;

interface EditableCellProps {
  value: string;
  isEdited: boolean;
  onCommit: (value: string) => void;
}

function EditableCell({ value, isEdited, onCommit }: EditableCellProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft]     = useState(value);
  const textareaRef           = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (editing && textareaRef.current) {
      textareaRef.current.focus();
      // Auto-resize on mount
      const ta = textareaRef.current;
      ta.style.height = 'auto';
      ta.style.height = ta.scrollHeight + 'px';
    }
  }, [editing]);

  // Keep draft in sync with external value changes (e.g. after retry)
  useEffect(() => {
    if (!editing) setDraft(value); // eslint-disable-line react-hooks/set-state-in-effect -- intentional sync from external value prop
  }, [value, editing]);

  const commit = () => {
    setEditing(false);
    const trimmed = draft.replace(/\n+$/, '');
    if (trimmed !== value) onCommit(trimmed);
  };

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setDraft(e.target.value);
    // Auto-resize on content change
    const ta = e.target;
    ta.style.height = 'auto';
    ta.style.height = ta.scrollHeight + 'px';
  };

  if (editing) {
    return (
      <textarea
        ref={textareaRef}
        value={draft}
        rows={1}
        onChange={handleChange}
        onBlur={commit}
        onKeyDown={(e) => {
          if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); commit(); }
          if (e.key === 'Escape') { setDraft(value); setEditing(false); }
        }}
        placeholder="Enter value..."
        className="w-full bg-transparent border-b border-archive-sepia/50 focus:outline-none font-serif text-sm text-archive-ink resize-none overflow-hidden"
      />
    );
  }

  return (
    <span
      onClick={() => { setDraft(value); setEditing(true); }}
      className={`cursor-text block w-full font-serif text-sm whitespace-pre-wrap ${isEdited ? 'text-archive-sepia font-semibold' : 'text-archive-ink/80'}`}
      title={isEdited ? 'Edited — click to change' : 'Click to edit'}
    >
      {value || <span className="text-archive-ink/30 italic">—</span>}
      {isEdited && <span className="ml-1 text-archive-sepia text-xs">•</span>}
    </span>
  );
}

const columnHelper = createColumnHelper<DisplayRow>();

export const ResultsTable: React.FC<ResultsTableProps> = ({
  results,
  fields,
  batchName,
  onRetryImage,
  isProcessing,
  retryingFilename,
  validationFilter = 'all',
}) => {
  const { updateResultCell } = useWizardStore();
  const [sorting, setSorting] = useState<SortingState>([]);
  const [lightboxSrc, setLightboxSrc] = useState<string | null>(null);

  // Filter results by validation status before expanding into display rows
  const filteredResults = useMemo(() => {
    if (validationFilter === 'all') return results;
    return results.filter((r) => {
      if (!r.validation) return validationFilter === 'all';
      const statuses = Object.values(r.validation).map((v) => v.status);
      if (validationFilter === 'invalid')   return statuses.includes('invalid');
      if (validationFilter === 'corrected') return statuses.includes('corrected');
      if (validationFilter === 'valid')     return statuses.length > 0 && statuses.every((s) => s === 'valid');
      return true;
    });
  }, [results, validationFilter]);

  // Expand multi-entry pages (Findmittel) into sub-rows.
  // Pages with _entries JSON array are expanded into N DisplayRows — one per entry.
  // Normal pages remain as single rows.
  const displayRows = useMemo<DisplayRow[]>(() => {
    const rows: DisplayRow[] = [];
    for (const row of filteredResults) {
      const entriesJson = row.data['_entries'];
      if (row.status === 'success' && entriesJson) {
        try {
          const entries = JSON.parse(entriesJson) as Record<string, string>[];
          const total = entries.length;
          if (total === 0) {
            rows.push({
              ...row,
              data: { '_entries': '[]', 'Hinweis': 'Keine Einträge erkannt' },
              _pageFilename: row.filename,
              _entryLabel: '0 Einträge',
              _isSubRow: false,
            });
          } else {
            entries.forEach((entry, idx) => {
              rows.push({
                ...row,
                // Unique virtual filename for per-entry cell editing
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
          rows.push({ ...row, _pageFilename: row.filename, _entryLabel: '', _isSubRow: false });
        }
      } else {
        rows.push({ ...row, _pageFilename: row.filename, _entryLabel: '', _isSubRow: false });
      }
    }
    return rows;
  }, [results]);

  const columns = [
    // Column 1: Thumbnail — text link, clicks open shared lightbox; shows entry label for multi-entry rows
    columnHelper.accessor('_pageFilename', {
      id: 'thumbnail',
      header: 'Image',
      enableSorting: true,
      cell: ({ row }) => {
        const r = row.original;
        if (r._isSubRow) {
          // Sub-rows: show entry label badge with indent
          return (
            <span className="font-mono text-xs text-archive-sepia/70 bg-archive-sepia/10 rounded px-1.5 py-0.5 ml-3 block self-start">
              Eintrag {r._entryLabel}
            </span>
          );
        }
        if (r._entryLabel) {
          // Primary row of a multi-entry page: show thumbnail + entry label below
          return (
            <div className="flex flex-col gap-1">
              <ThumbnailCell
                batchName={batchName}
                filename={r._pageFilename}
                onOpenLightbox={(src) => setLightboxSrc(src)}
              />
              <span className="font-mono text-xs text-archive-sepia/70 bg-archive-sepia/10 rounded px-1.5 py-0.5 self-start">
                Eintrag {r._entryLabel}
              </span>
            </div>
          );
        }
        return (
          <ThumbnailCell
            batchName={batchName}
            filename={r._pageFilename}
            onOpenLightbox={(src) => setLightboxSrc(src)}
          />
        );
      },
    }),
    // Column 2: Status — chip with error tooltip + retry button below for failed rows
    columnHelper.accessor('status', {
      header: 'Status',
      enableSorting: true,
      cell: ({ row }) => {
        const r = row.original;
        // Sub-rows inherit page status — only show on first sub-row
        if (r._isSubRow) return null;
        const s = r.status;
        const isRetrying = retryingFilename === r._pageFilename;
        return (
          <div className="flex flex-col items-start gap-1.5">
            <span
              className={`px-2 py-0.5 rounded text-xs uppercase tracking-widest font-semibold ${statusStyles[s]}`}
              title={r.error || undefined}
            >
              {s}
            </span>
            {s === 'failed' && (
              <button
                onClick={() => onRetryImage(r._pageFilename)}
                disabled={isProcessing || isRetrying}
                className="flex items-center gap-1 px-2 py-1 text-xs border border-parchment-dark rounded text-archive-ink/60 hover:text-archive-ink hover:border-archive-sepia transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {isRetrying
                  ? <Loader2 className="w-3 h-3 animate-spin" />
                  : <RotateCcw className="w-3 h-3" />}
                {isRetrying ? 'Retrying...' : 'Retry'}
              </button>
            )}
          </div>
        );
      },
    }),
    // Column 3: Duration
    columnHelper.accessor('duration', {
      header: 'Time',
      enableSorting: true,
      cell: ({ row }) => {
        if (row.original._isSubRow) return null;
        return (
          <span className="font-mono text-xs text-archive-ink/50">{row.original.duration.toFixed(1)}s</span>
        );
      },
    }),
    // Column 4: Extraction — all fields as key-value definition list (widest column last)
    columnHelper.display({
      id: 'extraction',
      header: 'Extraction',
      cell: ({ row }) => {
        const r = row.original;
        const visibleFields = fields.filter(f => !f.startsWith('_'));
        if (visibleFields.length === 0) return null;
        return (
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
            {visibleFields.map((field) => {
              const ocrValue = r.data[field] ?? '';
              const editedValue = r.editedData[field];
              const displayValue = editedValue !== undefined ? editedValue : ocrValue;
              return (
                <React.Fragment key={field}>
                  <dt className="font-mono text-xs text-archive-ink/50 whitespace-nowrap py-0.5">{field}</dt>
                  <dd className="py-0.5 flex items-start gap-1.5">
                    <ValidationBadge
                      outcome={r.validation?.[field]}
                      filename={r.filename}
                      field={field}
                    />
                    <EditableCell
                      value={displayValue}
                      isEdited={editedValue !== undefined && editedValue !== ocrValue}
                      onCommit={(v) => updateResultCell(r.filename, field, v)}
                    />
                  </dd>
                </React.Fragment>
              );
            })}
          </dl>
        );
      },
    }),
  ];

  const table = useReactTable({
    data: displayRows,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    // Unique row ID: virtual filename (contains __entry_N for sub-rows)
    getRowId: (row) => row.filename,
  });

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse">
        <thead>
          {table.getHeaderGroups().map((headerGroup) => (
            <tr key={headerGroup.id} className="border-b border-parchment-dark/40">
              {headerGroup.headers.map((header) => (
                <th
                  key={header.id}
                  onClick={header.column.getToggleSortingHandler()}
                  className={`px-4 py-2 text-left text-xs uppercase tracking-widest text-archive-ink/40 font-semibold whitespace-nowrap ${
                    header.column.getCanSort() ? 'cursor-pointer select-none hover:text-archive-sepia' : ''
                  }`}
                >
                  {flexRender(header.column.columnDef.header, header.getContext())}
                  {({ asc: ' ↑', desc: ' ↓' } as Record<string, string>)[header.column.getIsSorted() as string] ?? ''}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((row, i) => {
            const r = row.original;
            const isFirstSubRow = r._entryLabel && !r._isSubRow;
            return (
              <tr
                key={row.id}
                className={[
                  'border-b border-parchment-dark/20',
                  r._isSubRow
                    ? 'bg-parchment-light/5 border-l-2 border-l-archive-sepia/20'
                    : rowBg[r.status],
                  isFirstSubRow ? 'border-t-2 border-t-archive-sepia/20' : '',
                  !r._isSubRow && !r._entryLabel && i % 2 !== 0 ? 'bg-parchment-light/10' : '',
                ].filter(Boolean).join(' ')}
              >
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className="px-4 py-2 align-top">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
      {displayRows.length === 0 && (
        <p className="text-center py-8 text-archive-ink/40 italic">No results to display.</p>
      )}

      {/* Single shared Lightbox instance — opened by any ThumbnailCell click */}
      <Lightbox
        open={lightboxSrc !== null}
        close={() => setLightboxSrc(null)}
        slides={lightboxSrc ? [{ src: lightboxSrc }] : []}
      />
    </div>
  );
};
