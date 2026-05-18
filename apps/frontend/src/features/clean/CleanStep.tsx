import React, { useEffect, useMemo, useRef, useCallback, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { useBatchResultsRawQuery, useBatchConfigQuery, patchResult } from '../../api/batchesApi';
import type { AuditEntry } from '../../api/batchesApi';
import { useWizardStore } from '../../store/wizardStore';
import type { ResultRow, ValidationOutcome } from '../../store/wizardStore';
import { expandResults } from '../results/expandResults';
import type { DisplayRow } from '../results/expandResults';
import { useCleanState } from './useCleanState';
import type { UndoEntry } from './useCleanState';
import { ColumnList } from './ColumnList';
import { ColumnWorkspace } from './ColumnWorkspace';
import { AuditPanel } from './AuditPanel';
import { ClusterPicker } from './ClusterPicker';
import { FacetPanel } from './FacetPanel';
import { TransformBar } from './TransformBar';
import type { TransformOp } from './TransformBar';
import { buildClusters, computeFingerprint } from './fingerprint';
import type { ClusterGroup } from './fingerprint';
import { revalidateCell } from './validationRuntime';

// ── Transform helpers ─────────────────────────────────────────────────────────

function applyTransformOp(
  op: TransformOp,
  value: string,
  findPattern?: string,
  replaceWith?: string,
): string {
  // set-null is the only op valid on empty values
  if (!value && op !== 'set-null') return value;
  switch (op) {
    case 'trim':
      return value.trim();
    case 'upper':
      return value.toUpperCase();
    case 'lower':
      return value.toLowerCase();
    case 'title':
      // Unicode-aware: capitalize first letter of every letter-sequence word
      // Uses \p{L}+ for Unicode letter sequences (covers accented chars, non-Latin scripts)
      // Small words (von, de, der) are also capitalized — v1 intentional; curator responsible for domain-specific casing
      return value.replace(/\p{L}+/gu, (w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase());
    case 'collapse-ws':
      return value.replace(/\s+/g, ' ').trim();
    case 'regex-replace':
      if (!findPattern) return value;
      try {
        return value.replace(new RegExp(findPattern, 'gu'), replaceWith ?? '');
      } catch {
        return value;
      }
    case 'set-null':
      return '';
    default:
      return value;
  }
}

function opLabel(op: TransformOp): string {
  const labels: Record<TransformOp, string> = {
    trim: 'Trim',
    upper: 'Upper',
    lower: 'Lower',
    title: 'Title Case',
    'collapse-ws': 'Collapse whitespace',
    'regex-replace': 'Regex replace',
    'set-null': 'Set to NULL',
  };
  return labels[op] ?? op;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function CleanStep() {
  const batchId = useWizardStore((s) => s.batchId);
  const results = useWizardStore((s) => s.results);
  const setResults = useWizardStore((s) => s.setResults);
  const updateResultCell = useWizardStore((s) => s.updateResultCell);

  // Raw query gives access to {results, audit} full shape for AuditPanel hydration
  const { data: rawData, isLoading, error } = useBatchResultsRawQuery(batchId);

  // Config query — field_rules for client-side validation re-run
  const { data: configData } = useBatchConfigQuery(batchId);
  const fieldRules = configData?.field_rules ?? null;

  // Hydrate store from backend results on mount (same guard pattern as ResultsStep)
  const hydratedRef = useRef(false);
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
    facetState, setFacetState,
    undoStack, pushUndo, popUndo,
    serverAudit, setServerAudit,
    auditCollapsed, toggleAuditCollapsed,
  } = useCleanState();

  // AuditPanel expand/collapse tracking is already in useCleanState via auditCollapsed

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

  // ── Clusters ─────────────────────────────────────────────────────────────────

  // Compute clusters lazily when activeColumn changes
  const clusters = useMemo<ClusterGroup[]>(() => {
    if (!activeColumn) return [];
    return buildClusters(displayRows, activeColumn);
  }, [displayRows, activeColumn]);

  // Track skipped clusters per-column (reset on column change)
  const [skippedFingerprints, setSkippedFingerprints] = useState<Set<string>>(new Set());
  useEffect(() => {
    setSkippedFingerprints(new Set());
  }, [activeColumn]);

  // ── Faceted rows ──────────────────────────────────────────────────────────────

  const facetedRows = useMemo(() => {
    if (!activeColumn) return displayRows;
    let rows = displayRows.filter(r => {
      const v = (r.editedData?.[activeColumn] ?? r.data?.[activeColumn] ?? '') as string;
      return !!v?.trim();
    });
    // Text facet
    if (facetState.textValues.size > 0) {
      rows = rows.filter(r => {
        const v = (r.editedData?.[activeColumn] ?? r.data?.[activeColumn] ?? '') as string;
        return facetState.textValues.has(v);
      });
    }
    // Pattern facet (only if no pattern error and pattern is non-empty)
    if (!facetState.patternError && facetState.pattern) {
      try {
        const re = new RegExp(facetState.pattern, 'u');
        rows = rows.filter(r => {
          const v = (r.editedData?.[activeColumn] ?? r.data?.[activeColumn] ?? '') as string;
          return re.test(v);
        });
      } catch {
        // fallback: no pattern filter if malformed
      }
    }
    return rows;
  }, [displayRows, activeColumn, facetState]);

  // Debounce timers for PATCH calls (one timer per row+field combination)
  const patchTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  // ── Transform execution ───────────────────────────────────────────────────────

  const handleApplyTransform = useCallback((
    op: TransformOp,
    affectedRows: DisplayRow[],
    findPattern?: string,
    replaceWith?: string,
  ) => {
    if (!activeColumn || !batchId) return;

    const undoId = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
    const ts = new Date().toISOString();
    const cellSnapshot = new Map<string, { before: string; after: string }>();
    const statusSnapshot = new Map<string, { before: ValidationOutcome | null; after: ValidationOutcome | null }>();
    let affectedCount = 0;
    // CRITICAL: firstRowPatched MUST be flipped synchronously before any setTimeout is scheduled.
    // All setTimeout callbacks fire at ~the same delay and cannot reliably check this flag.
    let firstRowPatched = false;

    const auditEntry: AuditEntry = {
      id: undoId,
      ts,
      op: 'bulk-transform',
      column: activeColumn,
      label: `${opLabel(op)} on ${affectedRows.length} rows`,
      affected: affectedRows.length,
      scope: facetedRows.length < displayRows.filter(r => !!(r.editedData?.[activeColumn] ?? r.data?.[activeColumn])).length ? 'faceted' : 'all',
      facet_description: facetState.textValues.size > 0
        ? `text:${[...facetState.textValues].join(',')}`
        : facetState.pattern || undefined,
      source: 'bulk-transform',
    };

    for (const row of affectedRows) {
      const currentValue = (row.editedData?.[activeColumn] ?? row.data?.[activeColumn] ?? '') as string;
      const newValue = applyTransformOp(op, currentValue, findPattern, replaceWith);

      // PER-CELL NO-OP CHECK: if value unchanged, skip entirely.
      // This preserves 'verified' status on already-matching cells (e.g., Upper on already-uppercase "BERLIN").
      if (newValue === currentValue) continue;

      affectedCount++;

      // Snapshot before-state for undo
      const currentOutcome = (
        results.find(r => r.filename === row._pageFilename)?.validation?.[activeColumn]
      ) ?? null;
      cellSnapshot.set(row.filename, { before: currentValue, after: newValue });

      // Re-run client-side validation on transformed value
      const newOutcome = revalidateCell(activeColumn, newValue, currentValue, fieldRules, currentOutcome);
      statusSnapshot.set(row.filename, { before: currentOutcome, after: newOutcome });

      // Update Zustand editedData
      updateResultCell(row.filename, activeColumn, newValue);

      // Update validation outcome in Zustand results if it changed
      if (newOutcome !== currentOutcome) {
        useWizardStore.setState(state => ({
          results: state.results.map(r => {
            if (r.filename !== row._pageFilename) return r;
            return { ...r, validation: { ...r.validation, [activeColumn]: newOutcome } };
          }),
        }));
      }

      // SINGLE PATCH per cell: value + validation_status + audit_entry (ONLY on first row).
      // CRITICAL: Evaluate shouldCarryAudit and flip firstRowPatched SYNCHRONOUSLY here,
      // NOT inside the setTimeout callback. All setTimeout callbacks fire at ~500ms and
      // would all see firstRowPatched=false if the flag were checked inside callbacks.
      clearTimeout(patchTimers.current[row.filename + activeColumn]);
      const patchPayload = {
        field: activeColumn,
        value: newValue,
        validation_status: newOutcome?.status ?? null,
        audit_entry: !firstRowPatched ? auditEntry : undefined,
      };
      firstRowPatched = true; // flip immediately, before next iteration
      const filename = row.filename;
      const pageFilename = row._pageFilename;
      patchTimers.current[row.filename + activeColumn] = setTimeout(async () => {
        try {
          await patchResult(batchId, pageFilename, patchPayload);
        } catch (err) {
          console.warn('[CleanStep] PATCH failed for', filename, err);
        }
      }, 500);
    }

    if (affectedCount === 0) {
      toast.info('No changes — all selected rows already match the transform result.');
      return;
    }

    // Push to undo stack (session-only, ephemeral — never in Zustand partialize)
    const undoEntry: UndoEntry = {
      id: undoId,
      ts,
      op: 'bulk-transform',
      column: activeColumn,
      label: auditEntry.label,
      cellSnapshot,
      statusSnapshot,
    };
    pushUndo(undoEntry);
  }, [activeColumn, batchId, fieldRules, facetedRows, displayRows, facetState, results, updateResultCell, pushUndo]);

  // ── Cluster apply ─────────────────────────────────────────────────────────────

  const handleClusterApply = useCallback((fingerprint: string, canonical: string) => {
    if (!activeColumn || !batchId) return;
    const clusterGroup = clusters.find(c => c.fingerprint === fingerprint);
    if (!clusterGroup) return;

    // Rows to update: those whose current value has this fingerprint (and aren't already the canonical)
    const rowsToUpdate = displayRows.filter(r => {
      const v = (r.editedData?.[activeColumn] ?? r.data?.[activeColumn] ?? '') as string;
      return computeFingerprint(v) === fingerprint && v !== canonical;
    });

    if (rowsToUpdate.length === 0) {
      toast.info('All rows in this cluster already use the canonical value.');
      // Still remove from picker
      setSkippedFingerprints(prev => new Set([...prev, fingerprint]));
      return;
    }

    // 100-row confirmation for cluster apply too
    if (rowsToUpdate.length >= 100) {
      toast.warning(
        `This will merge ${rowsToUpdate.length} rows in "${activeColumn}" → "${canonical}".`,
        {
          description: 'Click Confirm to proceed.',
          action: {
            label: 'Confirm',
            onClick: () => executeClusterApply(fingerprint, canonical, clusterGroup, rowsToUpdate),
          },
          cancel: { label: 'Cancel', onClick: () => {} },
          duration: 10000,
        }
      );
      return;
    }

    executeClusterApply(fingerprint, canonical, clusterGroup, rowsToUpdate);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeColumn, batchId, clusters, displayRows, results, fieldRules, updateResultCell, pushUndo]);

  const executeClusterApply = useCallback((
    fingerprint: string,
    canonical: string,
    clusterGroup: ClusterGroup,
    rowsToUpdate: DisplayRow[],
  ) => {
    if (!activeColumn || !batchId) return;

    const undoId = `${Date.now().toString(36)}-cluster`;
    const ts = new Date().toISOString();
    const cellSnapshot = new Map<string, { before: string; after: string }>();
    const statusSnapshot = new Map<string, { before: ValidationOutcome | null; after: ValidationOutcome | null }>();
    // CRITICAL: firstRowPatched evaluated synchronously before any setTimeout is scheduled
    let firstRowPatched = false;

    const auditEntry: AuditEntry = {
      id: undoId,
      ts,
      op: 'cluster-merge',
      column: activeColumn,
      label: `Merge ${clusterGroup.rowCount} rows → "${canonical}"`,
      affected: rowsToUpdate.length,
      scope: 'all',
      source: 'cluster-merge',
    };

    for (const row of rowsToUpdate) {
      const currentValue = (row.editedData?.[activeColumn] ?? row.data?.[activeColumn] ?? '') as string;
      const currentOutcome = (
        results.find(r => r.filename === row._pageFilename)?.validation?.[activeColumn]
      ) ?? null;
      const newOutcome = revalidateCell(activeColumn, canonical, currentValue, fieldRules, currentOutcome);

      cellSnapshot.set(row.filename, { before: currentValue, after: canonical });
      statusSnapshot.set(row.filename, { before: currentOutcome, after: newOutcome });

      updateResultCell(row.filename, activeColumn, canonical);
      if (newOutcome !== currentOutcome) {
        useWizardStore.setState(state => ({
          results: state.results.map(r => {
            if (r.filename !== row._pageFilename) return r;
            return { ...r, validation: { ...r.validation, [activeColumn]: newOutcome } };
          }),
        }));
      }

      clearTimeout(patchTimers.current[row.filename + activeColumn]);

      // CRITICAL: Decide shouldCarryAudit and flip firstRowPatched SYNCHRONOUSLY before setTimeout.
      // Do NOT evaluate !firstRowPatched inside the setTimeout callback — all callbacks fire
      // concurrently at ~500ms and would all see false, producing N audit entries.
      const shouldCarryAudit = !firstRowPatched;
      firstRowPatched = true; // flip immediately, before next loop iteration

      const patchPayloadCluster = {
        field: activeColumn,
        value: canonical,
        validation_status: newOutcome?.status ?? null,
        audit_entry: shouldCarryAudit ? auditEntry : undefined,
      };
      const filename = row.filename;
      const pageFilename = row._pageFilename;
      patchTimers.current[row.filename + activeColumn] = setTimeout(async () => {
        try {
          await patchResult(batchId, pageFilename, patchPayloadCluster);
        } catch (err) {
          console.warn('[CleanStep] Cluster PATCH failed for', filename, err);
        }
      }, 500);
    }

    // Remove cluster from picker (mark as applied)
    setSkippedFingerprints(prev => new Set([...prev, fingerprint]));

    const undoEntry: UndoEntry = {
      id: undoId,
      ts,
      op: 'cluster-merge',
      column: activeColumn,
      label: auditEntry.label,
      cellSnapshot,
      statusSnapshot,
    };
    pushUndo(undoEntry);
  }, [activeColumn, batchId, results, fieldRules, updateResultCell, pushUndo]);

  // ── Undo execution ────────────────────────────────────────────────────────────

  const handleUndo = useCallback((entryId: string) => {
    const entry = popUndo(entryId);
    if (!entry || !batchId) return;

    for (const [virtualFilename, { before }] of entry.cellSnapshot) {
      // pageFilename = actual file (without __entry_N suffix) for PATCH calls
      const pageFilename = virtualFilename.includes('__entry_')
        ? virtualFilename.split('__entry_')[0]
        : virtualFilename;

      // Restore editedData in Zustand
      updateResultCell(virtualFilename, entry.column, before);

      // Restore validation status
      const beforeStatus = entry.statusSnapshot.get(virtualFilename)?.before;
      if (beforeStatus !== undefined) {
        useWizardStore.setState(state => ({
          results: state.results.map(r => {
            if (r.filename !== pageFilename) return r;
            return { ...r, validation: { ...r.validation, [entry.column]: beforeStatus } };
          }),
        }));
      }

      // Debounced PATCH to persist the revert
      // No audit_entry on undo — undo is implicit in the stack removal
      clearTimeout(patchTimers.current[virtualFilename + entry.column]);
      const col = entry.column;
      patchTimers.current[virtualFilename + entry.column] = setTimeout(async () => {
        await patchResult(batchId, pageFilename, {
          field: col,
          value: before,
          validation_status: beforeStatus?.status ?? null,
        }).catch(err => console.warn('[CleanStep] Undo PATCH failed', err));
      }, 500);
    }

    toast.success(`Undone: ${entry.label}`);
  }, [batchId, popUndo, updateResultCell]);

  // ── Render ────────────────────────────────────────────────────────────────────

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 py-24 text-archive-ink/50">
        <Loader2 className="w-8 h-8 animate-spin text-archive-sepia/60" />
        <p className="font-serif italic text-sm">Loading cleaning workspace...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 py-24 text-archive-ink/50">
        <p className="font-serif italic text-sm text-red-600/70">
          Failed to load batch results. Please try refreshing.
        </p>
      </div>
    );
  }

  if (!isLoading && results.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 py-24 text-archive-ink/40">
        <p className="font-serif italic text-sm">No results found for this batch.</p>
      </div>
    );
  }

  const activeColumnTotalRows = activeColumn
    ? displayRows.filter(r => !!(r.editedData?.[activeColumn] ?? r.data?.[activeColumn])).length
    : 0;

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
            clusterPickerSlot={activeColumn ? (
              <ClusterPicker
                clusters={clusters.filter(c => !skippedFingerprints.has(c.fingerprint))}
                onApply={handleClusterApply}
                onSkip={(fp) => setSkippedFingerprints(prev => new Set([...prev, fp]))}
                resetKey={activeColumn}
              />
            ) : null}
            facetPanelSlot={activeColumn ? (
              <FacetPanel
                displayRows={displayRows}
                field={activeColumn}
                facetState={facetState}
                onFacetChange={setFacetState}
                facetedRowCount={facetedRows.length}
              />
            ) : null}
            transformBarSlot={activeColumn ? (
              <TransformBar
                activeColumn={activeColumn}
                facetedRows={facetedRows}
                totalRows={activeColumnTotalRows}
                onApplyTransform={handleApplyTransform}
              />
            ) : null}
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
    </div>
  );
}
