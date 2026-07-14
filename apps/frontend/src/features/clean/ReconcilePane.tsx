import { useState } from 'react';
import axios from 'axios';
import { Link2 } from 'lucide-react';
import { toast } from 'sonner';
import { postReconcile } from '../../api/batchesApi';
import type { AuthorityType, ReconciliationOutcome } from '../../api/batchesApi';
import type { DisplayRow } from '../results/expandResults';
import { normalizeValue } from './validationRuntime';

const AUTHORITY_LABELS: Record<string, string> = {
  'gnd-persons': 'GND Persons',
  'gnd-places': 'GND Places',
  'gnd-subjects': 'GND Subjects',
  'gnd-corporate-bodies': 'GND Corporate Bodies',
  'gnd-works': 'GND Works',
  'wikidata': 'Wikidata',
  'geonames': 'GeoNames',
  'aat': 'Getty AAT',
};

interface ReconcilePaneProps {
  activeColumn: string | null;
  authorityType: string | null;        // from batch config authority_bindings[activeColumn]
  displayRows: DisplayRow[];           // all rows for the active column (from CleanStep)
  batchId: string | null;
  onCellReconciled: (
    pageFilename: string,
    field: string,
    outcome: ReconciliationOutcome | null,
    auditSource: string,
  ) => void;
  onOpenDrawer: (filename: string) => void;
}

export function ReconcilePane({
  activeColumn,
  authorityType,
  displayRows,
  batchId,
  onCellReconciled,
  onOpenDrawer,
}: ReconcilePaneProps) {
  const [isBulkRunning, setIsBulkRunning] = useState(false);
  const [bulkProgress, setBulkProgress] = useState({ done: 0, total: 0 });
  const [needsReview, setNeedsReview] = useState<string[]>([]);   // filenames needing manual pick
  const [reviewExpanded, setReviewExpanded] = useState(false);

  // No authority bound — show disabled message
  if (!authorityType) {
    return (
      <div className="border border-archive-200 rounded-lg mx-4 mt-3 p-3 bg-parchment-50/40">
        <div className="flex items-center gap-1.5">
          <Link2 size={14} className="text-archive-400" />
          <span className="text-xs text-archive-400 italic">
            No authority bound for this column — configure in the Configure step.
          </span>
        </div>
      </div>
    );
  }

  const runBulk = async (rows: DisplayRow[]) => {
    if (!activeColumn || !authorityType || !batchId) return;
    setIsBulkRunning(true);
    setBulkProgress({ done: 0, total: rows.length });
    const newNeedsReview: string[] = [];

    for (let i = 0; i < rows.length; i++) {
      const row = rows[i];
      const cellValue = (row.editedData?.[activeColumn] ?? row.data?.[activeColumn] ?? '') as string;
      setBulkProgress({ done: i + 1, total: rows.length });

      try {
        const { candidates } = await postReconcile(batchId, authorityType as AuthorityType, cellValue);
        // Auto-accept: exactly ONE candidate AND exact normalized label match.
        // IMPORT normalizeValue from validationRuntime — single source of truth, no duplication.
        if (
          candidates.length === 1 &&
          normalizeValue(candidates[0].label) === normalizeValue(cellValue)
        ) {
          const outcome: ReconciliationOutcome = {
            authority: authorityType,
            uri: candidates[0].uri,
            label: candidates[0].label,
            picked_by: 'auto',
            picked_at: new Date().toISOString(),
          };
          onCellReconciled(row._pageFilename, activeColumn, outcome, 'reconciliation-auto');
        } else {
          // Not auto-accepted — needs manual review
          newNeedsReview.push(row.filename);
        }
      } catch (err) {
        // API error (502/503 from endpoint) — treat as needs-review
        console.warn('[ReconcilePane] bulk reconcile error for cell', row.filename, err);
        newNeedsReview.push(row.filename);
      }
    }

    setNeedsReview(prev => [...new Set([...prev, ...newNeedsReview])]);
    setIsBulkRunning(false);
    toast.success(
      `Reconciled ${rows.length - newNeedsReview.length} cells automatically. ${newNeedsReview.length} need review.`
    );
  };

  const handleBulkReconcile = async () => {
    if (!activeColumn || !authorityType || !batchId) return;
    const rowsToReconcile = displayRows.filter(r => {
      const v = (r.editedData?.[activeColumn] ?? r.data?.[activeColumn] ?? '') as string;
      return !!v?.trim() && !r.validation?.[activeColumn]?.reconciliation;
    });
    if (rowsToReconcile.length === 0) {
      toast.info('All cells in this column are already reconciled or empty.');
      return;
    }

    // 100-row confirmation toast — same pattern as Phase 10 TransformBar
    if (rowsToReconcile.length >= 100) {
      toast.warning(
        `This will reconcile ${rowsToReconcile.length} cells in "${activeColumn}".`,
        {
          description: 'Bulk mode queries cells one at a time. May take several minutes for large batches.',
          action: { label: 'Confirm', onClick: () => runBulk(rowsToReconcile) },
          cancel: { label: 'Cancel', onClick: () => {} },
          duration: 10000,
        }
      );
      return;
    }
    runBulk(rowsToReconcile);
  };

  const handleClearCache = async () => {
    if (!batchId) return;
    try {
      await axios.delete(`/api/v1/batches/${batchId}/authority-cache`);
      toast.success('Authority cache cleared.');
    } catch (err) {
      console.warn('[ReconcilePane] Clear cache error', err);
      toast.error('Failed to clear authority cache.');
    }
  };

  const authorityLabel = AUTHORITY_LABELS[authorityType] ?? authorityType;

  return (
    <div className="border border-archive-200 rounded-lg mx-4 mt-3 p-3">
      {/* Header row */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-1.5">
          <Link2 size={14} className="text-archive-500" />
          <span className="text-xs font-semibold text-archive-700">
            Reconcile: {authorityLabel}
          </span>
        </div>
        <button
          onClick={handleClearCache}
          className="text-xs text-archive-500 hover:text-archive-700 transition-colors"
        >
          Clear cache
        </button>
      </div>

      {/* Bulk reconcile button */}
      <button
        onClick={handleBulkReconcile}
        disabled={isBulkRunning}
        className="w-full py-1.5 text-xs font-medium border border-archive-300 rounded text-archive-700 hover:bg-archive-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        {isBulkRunning
          ? `Querying ${bulkProgress.done} / ${bulkProgress.total}...`
          : 'Reconcile column'}
      </button>

      {/* Needs-review queue */}
      {needsReview.length > 0 && (
        <div className="mt-2">
          <button
            onClick={() => setReviewExpanded(v => !v)}
            className="text-xs text-amber-700 hover:text-amber-900 font-medium"
          >
            {needsReview.length} cell{needsReview.length !== 1 ? 's' : ''} need review
            {reviewExpanded ? ' (collapse)' : ' (expand)'}
          </button>
          {reviewExpanded && (
            <ul className="mt-1.5 flex flex-col gap-1 max-h-40 overflow-y-auto">
              {needsReview.map((filename) => {
                const row = displayRows.find(r => r.filename === filename);
                const cellValue = row
                  ? ((row.editedData?.[activeColumn!] ?? row.data?.[activeColumn!] ?? '') as string)
                  : filename;
                return (
                  <li key={filename}>
                    <button
                      onClick={() => onOpenDrawer(filename)}
                      className="text-xs text-archive-600 hover:text-archive-900 hover:underline text-left truncate w-full"
                      title={cellValue}
                    >
                      {cellValue || filename}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
