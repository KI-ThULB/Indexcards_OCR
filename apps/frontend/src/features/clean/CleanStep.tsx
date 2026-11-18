import { useEffect, useMemo, useRef, useCallback, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { useBatchResultsRawQuery, useBatchConfigQuery, useSyncedResultPatch, fetchResults, postReconcile } from '../../api/batchesApi';
import type { AuditEntry, AuthorityType, ReconcileCandidate, ReconciliationOutcome } from '../../api/batchesApi';
import { useWizardStore } from '../../store/wizardStore';
import type { ResultRow, ValidationOutcome } from '../../store/wizardStore';
import { expandResults } from '../results/expandResults';
import { looksLikeGroupValue } from '../results/groupValue';
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
import { ReconcilePane } from './ReconcilePane';
import { CandidateDrawer } from './CandidateDrawer';
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

// ── Authority labels ──────────────────────────────────────────────────────────

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

function sameMatch(left: ReconciliationOutcome | null, right: ReconciliationOutcome | null) {
  if (!left || !right) return left === right;
  return left.authority === right.authority && left.uri === right.uri && left.label === right.label
    && left.picked_by === right.picked_by && left.picked_at === right.picked_at;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function CleanStep() {
  const batchRevision = useWizardStore((s) => s.batchRevision);
  const batchId = useWizardStore((s) => s.batchId);
  const patchResult = useSyncedResultPatch();
  const results = useWizardStore((s) => s.results);
  const setResults = useWizardStore((s) => s.setResults);
  const updateResultCell = useWizardStore((s) => s.updateResultCell);

  // Raw query gives access to {results, audit} full shape for AuditPanel hydration
  const { data: rawData, isLoading, error } = useBatchResultsRawQuery(batchId);

  // Config query — field_rules for client-side validation re-run + authority_bindings for reconciliation
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
      editedData: { ...existingEditsMap.get(r.filename), ...r.edited_data },
      confidence: r.confidence ?? null,
      confidenceOverall: r.confidence_overall ?? null,
      duration: r.duration,
      validation: r.validation ?? null,
    }));

    setResults(rows, batchRevision);
  }, [rawData, results, setResults, batchRevision]);

  // Clean state (local — ephemeral, never in Zustand partialize)
  const {
    activeColumn, setActiveColumn,
    hiddenColumns, toggleHideColumn,
    facetState, setFacetState,
    undoStack, pushUndo, runUndo, undoBusy,
    serverAudit, setServerAudit,
    auditCollapsed, toggleAuditCollapsed,
  } = useCleanState();

  // AuditPanel expand/collapse tracking is already in useCleanState via auditCollapsed

  // Hydrate AuditPanel from checkpoint.json audit array on step entry
  useEffect(() => {
    if (rawData?.audit) {
      setServerAudit(rawData.audit);
    }
  }, [rawData?.audit, setServerAudit]);

  // Expand multi-entry rows for column view
  const displayRows = useMemo(() => expandResults(results), [results]);

  // Derive column list from display rows, preserving field order, excluding
  // _-prefixed internals and repeatable groups. A group holds a serialised
  // array, which is not a meaningful target for column-wise clustering,
  // faceting or regex replacement — its entries are curated in Verify.
  const columns = useMemo(() => {
    const fields = new Set<string>();
    for (const r of displayRows) {
      Object.keys(r.data)
        .filter(k => !k.startsWith('_') && !looksLikeGroupValue(r.data[k]))
        .forEach(f => fields.add(f));
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

  // ── Reconciliation authority binding ─────────────────────────────────────────

  // Read authority binding for activeColumn from batch config
  const activeColumnAuthority = activeColumn
    ? configData?.authority_bindings?.[activeColumn]?.type ?? null
    : null;

  // ── CandidateDrawer state ────────────────────────────────────────────────────

  type DrawerTarget = {
    batch: string;
    filename: string;
    field: string;
    authority: NonNullable<AuthorityType>;
    value: string;
  };
  const searchId = useRef(0);
  const [drawerState, setDrawerState] = useState<{
    target: DrawerTarget;
    query: string;
    candidates: ReconcileCandidate[];
    isLoading: boolean;
    isSaving: boolean;
    error: string | null;
  } | null>(null);
  const drawer = drawerState?.target.batch === batchId
    && drawerState.target.field === activeColumn
    && drawerState.target.authority === activeColumnAuthority ? drawerState : null;
  useEffect(() => () => { searchId.current++; }, [batchId, activeColumn, activeColumnAuthority]);

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
      const outcome = revalidateCell(activeColumn, newValue, currentValue, fieldRules, currentOutcome);
      const newOutcome = outcome?.reconciliation ? { ...outcome, reconciliation: null } : outcome;
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

      const patchPayload = {
        field: activeColumn,
        value: newValue,
        validation_status: newOutcome?.status ?? null,
        audit_entry: !firstRowPatched ? auditEntry : undefined,
      };
      firstRowPatched = true; // flip immediately, before next iteration
      const filename = row.filename;
      const pageFilename = row._pageFilename;
      void patchResult(batchId, pageFilename, patchPayload).catch(() => {
        toast.error(`Could not save changes to ${filename}.`);
      });
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
  }, [activeColumn, batchId, fieldRules, facetedRows, displayRows, facetState, results, updateResultCell, pushUndo, patchResult]);

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
  }, [activeColumn, batchId, clusters, displayRows, results, fieldRules, updateResultCell, pushUndo, patchResult]);

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
      const outcome = revalidateCell(activeColumn, canonical, currentValue, fieldRules, currentOutcome);
      const newOutcome = outcome?.reconciliation ? { ...outcome, reconciliation: null } : outcome;

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
      void patchResult(batchId, pageFilename, patchPayloadCluster).catch(() => {
        toast.error(`Could not save changes to ${filename}.`);
      });
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
  }, [activeColumn, batchId, results, fieldRules, updateResultCell, pushUndo, patchResult]);

  // ── Undo execution ────────────────────────────────────────────────────────────

  const attemptedUndo = useRef(new Set<string>());
  const handleUndo = (entryId: string) => {
    if (!batchId || useWizardStore.getState().batchRevision !== batchRevision) return;
    void runUndo(entryId, async entry => {
      const col = entry.column;
      const failed = await Promise.all(Array.from(entry.cellSnapshot, async ([filename, { before, after }]) => {
        const attemptKey = JSON.stringify([entryId, filename]);
        const beforeStatus = entry.statusSnapshot.get(filename)?.before;
        const previousMatch = beforeStatus?.reconciliation ?? null;
        const expectedMatch = entry.statusSnapshot.get(filename)?.after?.reconciliation ?? null;
        const shouldInspect = attemptedUndo.current.has(attemptKey);
        attemptedUndo.current.add(attemptKey);
        try {
          const current = useWizardStore.getState();
          const source = current.results.find(row => row.filename === filename);
          if (current.batchRevision !== batchRevision || !source || source.data['_entries']) return filename;
          const saved = await patchResult(batchId, filename, {
            field: col,
            value: before,
            expected_value: after,
            expected_reconciliation: expectedMatch,
            validation_status: beforeStatus?.status ?? null,
            ...(previousMatch ? { reconciliation: previousMatch } : { clear_reconciliation: true }),
          }, shouldInspect ? async () => {
            const { results } = await fetchResults(batchId);
            if (useWizardStore.getState().batchRevision !== batchRevision) throw new Error('Batch changed');
            const row = results.find(item => item.filename === filename);
            if (!row) throw new Error('Result no longer exists');
            const value = row.edited_data?.[col] ?? row.data?.[col] ?? '';
            const outcome = row.validation?.[col];
            const match = outcome?.reconciliation ?? null;
            if (value === before && sameMatch(match, previousMatch)
              && (!beforeStatus || outcome?.status === beforeStatus.status)) return row;
            if (value !== after || !sameMatch(match, expectedMatch)) throw new Error('Field changed after the transform');
          } : undefined);
          attemptedUndo.current.delete(attemptKey);
          useWizardStore.setState(state => {
            if (state.batchRevision !== batchRevision) return state;
            return {
              results: state.results.map(row => row.filename === filename
                && ((row.editedData[col] ?? row.data[col] ?? '') === after
                  || (row.editedData[col] ?? row.data[col] ?? '') === before)
                ? {
                  ...row,
                  editedData: { ...row.editedData, [col]: saved.edited_data?.[col] ?? before },
                  validation: { ...row.validation, [col]: saved.validation?.[col] ?? null },
                }
                : row),
            };
          });
          return null;
        } catch {
          return filename;
        }
      }));
      const remaining = failed.filter(name => name !== null);
      if (useWizardStore.getState().batchRevision === batchRevision) {
        if (remaining.length) toast.error('Some changes could not be undone. The remaining rows were kept for retry. Undo will check the saved values before retrying.');
        else toast.success(`Undone: ${entry.label}`);
      }
      return remaining;
    });
  };

  // ── Reconciliation handlers ───────────────────────────────────────────────────

  const closeDrawer = () => {
    searchId.current++;
    setDrawerState(null);
  };

  const searchCandidates = async (target: DrawerTarget, query: string) => {
    const id = ++searchId.current;
    setDrawerState({ target, query, candidates: [], isLoading: true, isSaving: false, error: null });
    try {
      const { candidates } = await postReconcile(target.batch, target.authority, query);
      if (id !== searchId.current || useWizardStore.getState().batchRevision !== batchRevision) return;
      setDrawerState({ target, query, candidates, isLoading: false, isSaving: false, error: null });
    } catch {
      if (id !== searchId.current || useWizardStore.getState().batchRevision !== batchRevision) return;
      setDrawerState({ target, query, candidates: [], isLoading: false, isSaving: false, error: 'API error — retry?' });
    }
  };

  const openDrawer = (filename: string) => {
    if (!activeColumn || !batchId || !activeColumnAuthority) return;
    const row = results.find(r => r.filename === filename);
    if (!row || row.data['_entries']) return;
    const value = row.editedData[activeColumn] ?? row.data[activeColumn] ?? '';
    void searchCandidates({ batch: batchId, filename, field: activeColumn, authority: activeColumnAuthority, value }, value);
  };

  const handleCellReconciled = useCallback(async (
    pageFilename: string,
    field: string,
    outcome: ReconciliationOutcome | null,
    auditSource: AuditEntry['source'],
    expectedValue: string,
  ): Promise<boolean> => {
    const state = useWizardStore.getState();
    if (!batchId || state.batchRevision !== batchRevision) return false;
    const row = state.results.find(result => result.filename === pageFilename);
    if (!row || (row.editedData[field] ?? row.data[field] ?? '') !== expectedValue) {
      toast.error('The field value changed. Search for candidates again.');
      return false;
    }
    const auditEntry: AuditEntry = {
      id: `${Date.now().toString(36)}-recon`,
      ts: new Date().toISOString(),
      op: 'reconciliation',
      column: field,
      label: outcome
        ? `Reconciled to ${outcome.label} (${auditSource.replace('reconciliation-', '')})`
        : `Reconciliation cleared (${auditSource.replace('reconciliation-', '')})`,
      affected: 1,
      scope: 'all',
      source: auditSource,
    };

    try {
      const saved = await patchResult(batchId, pageFilename, {
        field,
        expected_value: expectedValue,
        ...(outcome === null ? { clear_reconciliation: true } : { reconciliation: outcome }),
        audit_entry: auditEntry,
      });
      useWizardStore.setState(state => {
        if (state.batchRevision !== batchRevision) return state;
        return {
          results: state.results.map(row => {
            if (row.filename !== pageFilename || (row.editedData[field] ?? row.data[field] ?? '') !== expectedValue) return row;
            return { ...row, validation: { ...row.validation, [field]: saved.validation?.[field] ?? null } };
          }),
        };
      });
      return true;
    } catch {
      toast.error('Could not save reconciliation. Check the field value and try again.');
      return false;
    }
  }, [batchId, batchRevision, patchResult]);

  const saveSelection = async (candidate: ReconcileCandidate | null) => {
    if (!drawer || drawer.isLoading || drawer.isSaving) return;
    const { target } = drawer;
    const id = searchId.current;
    setDrawerState({ ...drawer, isSaving: true });
    const saved = await handleCellReconciled(target.filename, target.field, candidate ? {
      authority: target.authority,
      uri: candidate.uri,
      label: candidate.label,
      picked_by: 'manual',
      picked_at: new Date().toISOString(),
    } : null, candidate ? 'reconciliation-manual' : 'reconciliation-no-match', target.value);
    if (id !== searchId.current) return;
    if (saved) closeDrawer();
    else setDrawerState({ ...drawer, error: 'Could not save reconciliation. Try again.' });
  };

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
        onSelectColumn={(field) => {
          if (field !== activeColumn) closeDrawer();
          setActiveColumn(field);
        }}
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
            reconcilePaneSlot={activeColumn && !configData?.field_groups?.[activeColumn] ? (
              <ReconcilePane
                key={JSON.stringify([batchId, activeColumn, activeColumnAuthority])}
                activeColumn={activeColumn}
                authorityType={activeColumnAuthority}
                displayRows={displayRows.filter(r => r.status === 'success' && !r._entryLabel && !r.data['_entries'])}
                batchId={batchId}
                onCellReconciled={handleCellReconciled}
                onOpenDrawer={openDrawer}
              />
            ) : null}
          />

          {drawer && (
            <CandidateDrawer
              onClose={closeDrawer}
              cellValue={drawer.query}
              authority={AUTHORITY_LABELS[drawer.target.authority] ?? drawer.target.authority}
              candidates={drawer.candidates}
              isLoading={drawer.isLoading}
              isSaving={drawer.isSaving}
              error={drawer.error}
              onPick={saveSelection}
              onNoMatch={() => saveSelection(null)}
              onSearchAgain={(query) => searchCandidates(drawer.target, query)}
            />
          )}
        </div>

        {/* Audit panel — collapsible bottom bar */}
        <AuditPanel
          serverEntries={serverAudit}
          sessionEntries={undoStack}
          onUndo={handleUndo}
          undoBusy={undoBusy}
          isCollapsed={auditCollapsed}
          onToggleCollapse={toggleAuditCollapsed}
        />
      </div>
    </div>
  );
}
