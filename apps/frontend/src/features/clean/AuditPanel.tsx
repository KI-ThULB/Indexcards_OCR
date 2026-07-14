import React, { useMemo } from 'react';
import { History, ChevronDown, Undo2 } from 'lucide-react';
import type { AuditEntry } from '../../api/batchesApi';
import type { UndoEntry } from './useCleanState';

interface AuditPanelProps {
  serverEntries: AuditEntry[];         // hydrated from checkpoint.json on CleanStep entry
  sessionEntries: UndoEntry[];         // current-session in-memory undo stack from useCleanState
  onUndo: (entryId: string) => void;   // callback — wired in 10-04; stub here
  isCollapsed: boolean;
  onToggleCollapse: () => void;
}

interface DisplayEntry {
  id: string;
  ts: string;
  label: string;
  column: string;
  isSession: boolean;
}

export const AuditPanel: React.FC<AuditPanelProps> = ({
  serverEntries,
  sessionEntries,
  onUndo,
  isCollapsed,
  onToggleCollapse,
}) => {
  // Merge and sort session + server entries, most recent first
  const merged = useMemo<DisplayEntry[]>(() => {
    const session: DisplayEntry[] = sessionEntries.map((e) => ({
      id: e.id,
      ts: e.ts,
      label: e.label,
      column: e.column,
      isSession: true,
    }));
    const server: DisplayEntry[] = serverEntries.map((e) => ({
      id: e.id,
      ts: e.ts,
      label: e.label,
      column: e.column,
      isSession: false,
    }));
    // Combine and sort descending by timestamp
    return [...session, ...server].sort(
      (a, b) => new Date(b.ts).getTime() - new Date(a.ts).getTime()
    );
  }, [sessionEntries, serverEntries]);

  const totalCount = merged.length;

  return (
    <div className="shrink-0 border-t border-archive-200">
      {/* Panel header — always visible, click to toggle */}
      <div
        className="flex items-center gap-2 px-3 py-2 cursor-pointer select-none bg-parchment-50 border-t border-archive-200"
        onClick={onToggleCollapse}
        role="button"
        aria-expanded={!isCollapsed}
        aria-label="Toggle cleaning history panel"
      >
        <History className="w-4 h-4 text-archive-500 shrink-0" />
        <span className="text-xs font-semibold text-archive-600 uppercase tracking-wide">History</span>
        <span className="ml-1 text-xs bg-archive-200 text-archive-700 rounded-full px-1.5 py-0.5">
          {totalCount}
        </span>
        <ChevronDown
          className={`ml-auto w-4 h-4 text-archive-400 transition-transform duration-200 ${
            isCollapsed ? '' : 'rotate-180'
          }`}
        />
      </div>

      {/* Entry list — visible only when expanded */}
      {!isCollapsed && (
        <div className="max-h-48 overflow-y-auto bg-white">
          {merged.length === 0 ? (
            <p className="px-3 py-4 text-xs text-archive-400 text-center">
              No cleaning history yet.
            </p>
          ) : (
            merged.map((entry) => (
              <div
                key={entry.id}
                className="flex items-start gap-2 px-3 py-2 border-b border-archive-100 last:border-0 text-xs"
              >
                <div className="flex-1 min-w-0">
                  <span className="font-medium text-archive-700">{entry.label}</span>
                  <span className="ml-1 text-archive-400">on {entry.column}</span>
                  <div className="text-archive-400 mt-0.5">
                    {new Date(entry.ts).toLocaleString()}
                  </div>
                </div>
                {entry.isSession && (
                  <button
                    onClick={() => onUndo(entry.id)}
                    className="flex items-center gap-1 text-xs text-archive-600 hover:text-red-600 px-2 py-0.5 rounded border border-archive-300 hover:border-red-400 transition-colors shrink-0"
                    title="Undo this operation"
                  >
                    <Undo2 size={12} />
                    Undo
                  </button>
                )}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
};
