import React, { useMemo } from 'react';
import { Scissors } from 'lucide-react';
import type { DisplayRow } from '../results/expandResults';
import type { FacetState } from './useCleanState';

interface ColumnWorkspaceProps {
  activeColumn: string | null;
  displayRows: DisplayRow[];
  facetState: FacetState;
  onFacetChange: (fs: FacetState) => void;
  // Slots for Wave 2/3 content (accept ReactNode so plans 10-03 and 10-04 can inject):
  clusterPickerSlot?: React.ReactNode;
  facetPanelSlot?: React.ReactNode;
  transformBarSlot?: React.ReactNode;
  reconcilePaneSlot?: React.ReactNode;   // Phase 11 — authority reconciliation pane
}

export const ColumnWorkspace: React.FC<ColumnWorkspaceProps> = ({
  activeColumn,
  displayRows,
  facetState,
  clusterPickerSlot,
  facetPanelSlot,
  transformBarSlot,
  reconcilePaneSlot,
}) => {
  // Rows with a non-empty value for the active column
  const activeRows = useMemo(() => {
    if (!activeColumn) return [];
    return displayRows.filter((r) => {
      const val = r.editedData?.[activeColumn] ?? r.data?.[activeColumn] ?? '';
      return val !== '' && val != null;
    });
  }, [activeColumn, displayRows]);

  // Facet-filtered rows (applied on top of activeRows)
  const facetedRows = useMemo(() => {
    if (!activeColumn) return [];
    let rows = activeRows;

    // Text facet: filter by selected values
    if (facetState.textValues.size > 0) {
      rows = rows.filter((r) => {
        const val = (r.editedData?.[activeColumn] ?? r.data?.[activeColumn] ?? '') as string;
        return facetState.textValues.has(val);
      });
    }

    // Pattern facet: filter by regex
    if (facetState.pattern && !facetState.patternError) {
      try {
        const re = new RegExp(facetState.pattern, 'u');
        rows = rows.filter((r) => {
          const val = (r.editedData?.[activeColumn] ?? r.data?.[activeColumn] ?? '') as string;
          return re.test(val);
        });
      } catch {
        // malformed regex — no filter applied (patternError should be set by caller)
      }
    }

    return rows;
  }, [activeColumn, activeRows, facetState]);

  const facetActive = facetState.textValues.size > 0 || (facetState.pattern.length > 0 && !facetState.patternError);

  // Empty state when no column selected
  if (activeColumn === null) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-archive-400 gap-2">
        <Scissors className="w-10 h-10 opacity-30" />
        <p className="text-sm">Select a column to start cleaning</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Column header */}
      <div className="flex items-center px-4 py-2 border-b border-archive-200 bg-parchment-50 shrink-0">
        <h2 className="text-sm font-semibold text-archive-800">{activeColumn}</h2>
        <span className="ml-2 text-xs text-archive-400">
          {activeRows.length} rows{facetActive ? ` (${facetedRows.length} filtered)` : ''}
        </span>
      </div>

      {/* Slot areas — plugged in by Plans 10-03, 10-04, and 11-04 */}
      <div className="flex-1 overflow-y-auto flex flex-col gap-0">
        {transformBarSlot}
        {reconcilePaneSlot}   {/* Phase 11 — authority reconciliation pane */}
        {clusterPickerSlot}
        {facetPanelSlot}

        {/* Placeholder message when no slots are injected yet */}
        {!transformBarSlot && !reconcilePaneSlot && !clusterPickerSlot && !facetPanelSlot && (
          <div className="flex flex-col items-center justify-center h-full text-archive-300 gap-2 py-12">
            <p className="text-xs italic">Transform, cluster, and facet tools appear here.</p>
          </div>
        )}
      </div>
    </div>
  );
};

// Export facetedRows computation for use by parent if needed
export type { ColumnWorkspaceProps };
