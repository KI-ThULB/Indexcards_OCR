import { useState, useCallback } from 'react';
import { AlignLeft } from 'lucide-react';
import { toast } from 'sonner';
import type { DisplayRow } from '../results/expandResults';
import { RegexReplaceModal } from './RegexReplaceModal';

export type TransformOp =
  | 'trim'
  | 'upper'
  | 'lower'
  | 'title'
  | 'collapse-ws'
  | 'regex-replace'
  | 'set-null';

interface TransformBarProps {
  activeColumn: string | null;
  facetedRows: DisplayRow[];       // rows currently passing facet filter (transform scope)
  totalRows: number;               // total rows in active column (for scope display)
  onApplyTransform: (
    transform: TransformOp,
    affectedRows: DisplayRow[],
    findPattern?: string,          // for Regex Replace
    replaceWith?: string,          // for Regex Replace
  ) => void;
}

const TRANSFORMS: Array<{ op: TransformOp; label: string; title: string }> = [
  { op: 'trim',          label: 'Trim',           title: 'Remove leading/trailing whitespace' },
  { op: 'upper',         label: 'UPPER',          title: 'Convert to UPPERCASE' },
  { op: 'lower',         label: 'lower',          title: 'Convert to lowercase' },
  { op: 'title',         label: 'Title Case',     title: 'Capitalize first letter of each word' },
  { op: 'collapse-ws',   label: 'Collapse spaces', title: 'Replace multiple spaces with single space' },
  { op: 'regex-replace', label: 'Regex…',         title: 'Find and replace using regular expressions' },
  { op: 'set-null',      label: 'Set to NULL',    title: 'Clear the cell value (set to empty/null)' },
];

/**
 * TransformBar: 7 bulk-transform buttons.
 * Applies the selected transform to the currently faceted rows of the active column.
 *
 * 100-row guard: shows a sonner toast.warning confirmation before applying any transform
 * that would affect 100+ rows — same pattern as the Phase 8 export gate.
 *
 * Regex Replace opens a modal for find/replace inputs with a try/catch regex guard.
 */
export function TransformBar({
  activeColumn,
  facetedRows,
  totalRows,
  onApplyTransform,
}: TransformBarProps) {
  const [modalOpen, setModalOpen] = useState(false);

  const handleTransform = useCallback((op: TransformOp) => {
    if (!activeColumn || facetedRows.length === 0) return;

    // Regex Replace: open the modal for pattern input
    if (op === 'regex-replace') {
      setModalOpen(true);
      return;
    }

    // 100+ row confirmation toast
    if (facetedRows.length >= 100) {
      toast.warning(
        `This will transform ${facetedRows.length} rows in "${activeColumn}".`,
        {
          description: 'Click Confirm to proceed.',
          action: {
            label: 'Confirm',
            onClick: () => onApplyTransform(op, facetedRows),
          },
          cancel: { label: 'Cancel', onClick: () => {} },
          duration: 10000,
        }
      );
      return;
    }

    onApplyTransform(op, facetedRows);
  }, [activeColumn, facetedRows, onApplyTransform]);

  const handleModalApply = useCallback((findPattern: string, replaceWith: string) => {
    if (!activeColumn || facetedRows.length === 0) return;

    // 100+ row confirmation toast for Regex Replace too
    if (facetedRows.length >= 100) {
      toast.warning(
        `This will transform ${facetedRows.length} rows in "${activeColumn}".`,
        {
          description: 'Click Confirm to proceed.',
          action: {
            label: 'Confirm',
            onClick: () => onApplyTransform('regex-replace', facetedRows, findPattern, replaceWith),
          },
          cancel: { label: 'Cancel', onClick: () => {} },
          duration: 10000,
        }
      );
      return;
    }

    onApplyTransform('regex-replace', facetedRows, findPattern, replaceWith);
  }, [activeColumn, facetedRows, onApplyTransform]);

  const isDisabled = !activeColumn || facetedRows.length === 0;
  const isFiltered = facetedRows.length < totalRows;

  return (
    <>
      <div className="border border-archive-200 rounded-lg mx-4 mt-3 p-3">
        {/* Header */}
        <div className="flex items-center gap-1.5 mb-2">
          <AlignLeft size={13} className="text-archive-500" />
          <span className="text-xs font-semibold text-archive-700 uppercase tracking-wide">
            Transforms
          </span>
        </div>

        {/* Scope display */}
        <div className="text-xs text-archive-500 mb-2">
          Scope:{' '}
          <strong>{facetedRows.length}</strong> of {totalRows} rows
          {isFiltered && (
            <span className="ml-1 text-amber-700">(filtered)</span>
          )}
        </div>

        {/* Transform buttons */}
        <div className="flex flex-wrap gap-1.5">
          {TRANSFORMS.map((t) => (
            <button
              key={t.op}
              onClick={() => handleTransform(t.op)}
              disabled={isDisabled}
              title={t.title}
              className="px-2.5 py-1 text-xs rounded border border-archive-300 text-archive-700
                         hover:bg-archive-100 hover:text-archive-900 transition-colors
                         disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Regex Replace modal */}
      <RegexReplaceModal
        isOpen={modalOpen}
        onClose={() => setModalOpen(false)}
        onApply={handleModalApply}
      />
    </>
  );
}
