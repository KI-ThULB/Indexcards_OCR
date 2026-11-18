import { useState, useCallback, useRef } from 'react';
import type { AuditEntry } from '../../api/batchesApi';

export interface UndoEntry {
  id: string;                                           // stable ID (matches audit entry id)
  ts: string;                                           // ISO timestamp
  op: 'bulk-transform' | 'cluster-merge' | 'reconciliation';
  column: string;
  label: string;                                        // "Upper on 42 rows"
  // Per-cell snapshot for reverting: Map<virtualFilename, {before, after}>
  // virtualFilename = filename for single-entry, `${filename}__entry_N` for multi-entry
  cellSnapshot: Map<string, { before: string; after: string }>;
  // Validation status snapshot for reverting
  statusSnapshot: Map<string, { before: import('../../api/batchesApi').ValidationOutcome | null; after: import('../../api/batchesApi').ValidationOutcome | null }>;
}

export interface FacetState {
  textValues: Set<string>;    // selected values in text facet (empty = no filter)
  pattern: string;            // regex string for pattern facet (empty = no filter)
  patternError: boolean;      // true if pattern is malformed regex
}

export function useCleanState() {
  const [activeColumn, setActiveColumn] = useState<string | null>(null);
  const [hiddenColumns, setHiddenColumns] = useState<Set<string>>(new Set());
  const [facetState, setFacetState] = useState<FacetState>({
    textValues: new Set(),
    pattern: '',
    patternError: false,
  });
  const [undoStack, setUndoStack] = useState<UndoEntry[]>([]);
  // serverAudit is loaded from checkpoint.json on CleanStep mount — NOT the undo stack
  // These are historical entries from prior sessions (read-only in the UI)
  const [serverAudit, setServerAudit] = useState<AuditEntry[]>([]);
  // Audit panel collapse state
  const [auditCollapsed, setAuditCollapsed] = useState(true);

  const toggleHideColumn = useCallback((column: string) => {
    setHiddenColumns(prev => {
      const next = new Set(prev);
      if (next.has(column)) { next.delete(column); } else { next.add(column); }
      return next;
    });
  }, []);

  const pushUndo = useCallback((entry: UndoEntry) => {
    setUndoStack(prev => [entry, ...prev]); // most recent first
  }, []);

  const undoInProgress = useRef(false);
  const [undoBusy, setUndoBusy] = useState(false);

  const runUndo = async (entryId: string, restore: (entry: UndoEntry) => Promise<string[]>) => {
    const entry = undoStack.find(item => item.id === entryId);
    if (!entry || undoInProgress.current) return;
    undoInProgress.current = true;
    setUndoBusy(true);
    try {
      const remaining = new Set(await restore(entry));
      setUndoStack(stack => stack.flatMap(item => {
        if (item.id !== entryId) return [item];
        if (!remaining.size) return [];
        return [{
          ...item,
          cellSnapshot: new Map([...item.cellSnapshot].filter(([name]) => remaining.has(name))),
        }];
      }));
    } finally {
      undoInProgress.current = false;
      setUndoBusy(false);
    }
  };

  const clearFacet = useCallback(() => {
    setFacetState({ textValues: new Set(), pattern: '', patternError: false });
  }, []);

  const toggleAuditCollapsed = useCallback(() => {
    setAuditCollapsed(prev => !prev);
  }, []);

  return {
    activeColumn, setActiveColumn,
    hiddenColumns, toggleHideColumn,
    facetState, setFacetState, clearFacet,
    undoStack, pushUndo, runUndo, undoBusy,
    serverAudit, setServerAudit,
    auditCollapsed, toggleAuditCollapsed,
  };
}
