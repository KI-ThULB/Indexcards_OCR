import React, { useEffect, useMemo } from 'react';
import { Loader2 } from 'lucide-react';
import { useBatchResultsRawQuery, useBatchConfigQuery } from '../../api/batchesApi';
import { useWizardStore } from '../../store/wizardStore';
import type { ResultRow } from '../../store/wizardStore';
import { expandResults } from '../results/expandResults';
import { useCleanState } from './useCleanState';
import { ColumnList } from './ColumnList';
import { ColumnWorkspace } from './ColumnWorkspace';
import { AuditPanel } from './AuditPanel';

export function CleanStep() {
  const batchId = useWizardStore((s) => s.batchId);
  const results = useWizardStore((s) => s.results);
  const setResults = useWizardStore((s) => s.setResults);

  // Raw query gives access to {results, audit} full shape for AuditPanel hydration
  const { data: rawData, isLoading, error } = useBatchResultsRawQuery(batchId);

  // Config query — field_rules for client-side validation re-run (Plan 10-04)
  const { data: batchConfig } = useBatchConfigQuery(batchId);

  // Hydrate store from backend results on mount (same guard pattern as ResultsStep)
  const hydratedRef = React.useRef(false);
  useEffect(() => {
    if (!rawData?.results || hydratedRef.current) return;
    hydratedRef.current = true;

    const existingEditsMap = new Map<string, Record<string, string>>(
      results.map((r) => [r.filename, r.editedData])
    );

    const rows: ResultRow[] = rawData.results.map((r) => ({
      filename: r.filename,
      status: r.success ? 'success' : 'failed',
      error: r.error ?? undefined,
      data: r.data ?? {},
      editedData: existingEditsMap.get(r.filename) ?? {},
      duration: r.duration,
      validation: r.validation ?? null,
    }));

    setResults(rows);
  }, [rawData, results, setResults]);

  // Clean state (local — ephemeral, never in Zustand partialize)
  const {
    activeColumn, setActiveColumn,
    hiddenColumns, toggleHideColumn,
    facetState, setFacetState, clearFacet,
    undoStack, pushUndo, popUndo,
    serverAudit, setServerAudit,
    auditCollapsed, toggleAuditCollapsed,
  } = useCleanState();

  // Hydrate AuditPanel from checkpoint.json audit array on step entry
  useEffect(() => {
    if (rawData?.audit && rawData.audit.length > 0) {
      setServerAudit(rawData.audit);
    }
  }, [rawData?.audit, setServerAudit]);

  // Expand multi-entry rows for column view
  const displayRows = useMemo(() => expandResults(results), [results]);

  // Derive column list from display rows, preserving field order, excluding _-prefixed internals
  const columns = useMemo(() => {
    const fields = new Set<string>();
    for (const r of displayRows) {
      Object.keys(r.data).filter(k => !k.startsWith('_')).forEach(f => fields.add(f));
    }
    return [...fields];
  }, [displayRows]);

  // Visible columns (not hidden)
  const visibleColumns = useMemo(
    () => columns.filter(c => !hiddenColumns.has(c)),
    [columns, hiddenColumns]
  );

  // Undo handler stub — wired in Plan 10-04
  const handleUndo = (entryId: string) => {
    const entry = popUndo(entryId);
    if (!entry) return;
    // TODO (Plan 10-04): revert cellSnapshot + statusSnapshot in Zustand, fire PATCHes
    console.warn('[CleanStep] Undo not yet wired — entry:', entry);
  };

  // Loading state
  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 py-24 text-archive-ink/50">
        <Loader2 className="w-8 h-8 animate-spin text-archive-sepia/60" />
        <p className="font-serif italic text-sm">Loading cleaning workspace...</p>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 py-24 text-archive-ink/50">
        <p className="font-serif italic text-sm text-red-600/70">
          Failed to load batch results. Please try refreshing.
        </p>
      </div>
    );
  }

  // Empty state
  if (!isLoading && results.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 py-24 text-archive-ink/40">
        <p className="font-serif italic text-sm">No results found for this batch.</p>
      </div>
    );
  }

  return (
    <div className="flex h-full overflow-hidden">
      {/* Left sidebar: column list */}
      <ColumnList
        columns={visibleColumns}
        activeColumn={activeColumn}
        hiddenColumns={hiddenColumns}
        onSelectColumn={setActiveColumn}
        onToggleHide={toggleHideColumn}
        displayRows={displayRows}
      />

      {/* Right pane: workspace + audit panel */}
      <div className="flex flex-col flex-1 overflow-hidden">
        {/* Column workspace (grows to fill space above audit panel) */}
        <div className="flex-1 overflow-hidden">
          <ColumnWorkspace
            activeColumn={activeColumn}
            displayRows={displayRows}
            facetState={facetState}
            onFacetChange={setFacetState}
            // clusterPickerSlot, facetPanelSlot, transformBarSlot injected in Plans 10-03/10-04
          />
        </div>

        {/* Audit panel — collapsible bottom bar */}
        <AuditPanel
          serverEntries={serverAudit}
          sessionEntries={undoStack}
          onUndo={handleUndo}
          isCollapsed={auditCollapsed}
          onToggleCollapse={toggleAuditCollapsed}
        />
      </div>

      {/* Pass fieldRules via batchConfig for Plan 10-04 usage */}
      {/* batchConfig?.field_rules is available here for transform re-validation */}
      {/* eslint-disable-next-line @typescript-eslint/no-unused-vars */}
      {batchConfig && null /* consumed by Plan 10-04 TransformBar via prop drilling or context */}

      {/* Pass pushUndo for Plan 10-04 */}
      {/* pushUndo and clearFacet available in closure for child component wiring */}
    </div>
  );
}
