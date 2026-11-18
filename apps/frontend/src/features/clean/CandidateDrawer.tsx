import { useState, useEffect, useLayoutEffect, useRef } from 'react';
import { X, Link2, Search, AlertCircle, Loader2 } from 'lucide-react';
import type { ReconcileCandidate } from '../../api/batchesApi';

interface CandidateDrawerProps {
  onClose: () => void;
  cellValue: string;         // current cell value (original query)
  authority: string;         // authority type label (for header display)
  candidates: ReconcileCandidate[];
  isLoading: boolean;
  isSaving: boolean;
  error: string | null;      // "API error — retry?" or null
  onPick: (candidate: ReconcileCandidate) => void;
  onNoMatch: () => void;
  onSearchAgain: (refinedQuery: string) => void;
}

export function CandidateDrawer({
  onClose,
  cellValue,
  authority,
  candidates,
  isLoading,
  isSaving,
  error,
  onPick,
  onNoMatch,
  onSearchAgain,
}: CandidateDrawerProps) {
  const [refinedQuery, setRefinedQuery] = useState(cellValue);

  // Sync refinedQuery when cellValue changes (e.g., Search again updates the query)
  useEffect(() => {
    setRefinedQuery(cellValue);
  }, [cellValue]);

  const dialogRef = useRef<HTMLDialogElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  useLayoutEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const opener = document.activeElement;
    dialog.showModal();
    closeRef.current?.focus();
    return () => {
      dialog.close();
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus();
      else document.getElementById('clean-reconcile-run')?.focus();
    };
  }, []);

  return (
    <dialog
      ref={dialogRef}
      className="fixed inset-x-0 bottom-0 top-auto m-0 mx-auto mb-4 w-[calc(100%-2rem)] max-w-lg overflow-hidden rounded-xl border border-parchment-dark bg-archive-paper p-0 text-archive-ink shadow-xl backdrop:bg-black/30"
      aria-modal="true"
      aria-label={`Reconcile: ${cellValue}`}
      aria-busy={isLoading || isSaving}
      onCancel={(event) => {
        event.preventDefault();
        if (!isSaving) onClose();
      }}
    >
      <div className="flex max-h-[min(36rem,calc(100dvh-2rem))] flex-col overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-parchment-dark shrink-0">
          <div className="flex items-center gap-2 min-w-0">
            <Link2 size={14} className="text-archive-ink shrink-0" />
            <span className="text-sm font-semibold text-archive-ink truncate">
              Reconcile: {cellValue}
            </span>
            <span className="text-xs text-archive-ink ml-1 shrink-0">via {authority}</span>
          </div>
          <button
            ref={closeRef}
            onClick={onClose}
            disabled={isSaving}
            className="text-archive-ink hover:text-archive-sepia shrink-0 ml-2"
            aria-label="Close candidate drawer"
          >
            <X size={16} />
          </button>
        </div>

        {/* Content */}
        <div className="min-h-16 flex-1 overflow-y-auto p-3">
          {(isLoading || isSaving) && (
            <div role="status" className="flex items-center gap-2 text-sm text-archive-ink/80 py-4 justify-center">
              <Loader2 size={16} className="animate-spin" />
              <span>{isSaving ? 'Saving reconciliation…' : `Querying ${authority}…`}</span>
            </div>
          )}
          {error && !isLoading && (
            <div role="alert" className="flex items-center gap-2 text-sm text-red-700 bg-red-50 rounded p-3 mb-3">
              <AlertCircle size={14} className="shrink-0" />
              <span>{error}</span>
            </div>
          )}
          {!isLoading && !error && candidates.length === 0 && (
            <p className="text-sm text-archive-ink py-4 text-center">No candidates found.</p>
          )}
          {!isLoading &&
            candidates.map((c, i) => (
              <div
                key={i}
                className="flex items-start gap-3 py-2.5 border-b border-parchment-dark last:border-0"
              >
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-archive-ink">{c.label}</p>
                  {c.description && (
                    <p className="text-xs text-archive-ink mt-0.5 break-words">{c.description}</p>
                  )}
                  <a
                    href={c.uri}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-blue-600 hover:underline break-all block mt-0.5"
                  >
                    {c.uri}
                  </a>
                </div>
                <button
                  onClick={() => onPick(c)}
                  aria-label={`Pick ${c.label}`}
                  disabled={isSaving}
                  className="shrink-0 px-2.5 py-1 text-xs bg-archive-sepia text-parchment-light rounded hover:bg-archive-ink whitespace-nowrap"
                >
                  Pick this
                </button>
              </div>
            ))}
        </div>

        {/* Footer: Search again + No match */}
        <div className="p-3 border-t border-parchment-dark flex flex-col gap-2 shrink-0">
          <div className="flex gap-2">
            <input
              type="text"
              value={refinedQuery}
              onChange={(e) => setRefinedQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !isSaving && refinedQuery.trim()) onSearchAgain(refinedQuery);
              }}
              aria-label="Refine candidate search"
              disabled={isSaving}
              placeholder="Search again with different query..."
              className="min-w-0 flex-1 border border-parchment-dark rounded px-2 py-1.5 text-sm bg-parchment-light text-archive-ink focus:outline-none focus:ring-1 focus:ring-archive-sepia"
            />
            <button
              onClick={() => onSearchAgain(refinedQuery)}
              disabled={isSaving || !refinedQuery.trim()}
              className="px-2.5 py-1.5 border border-parchment-dark rounded text-archive-ink hover:bg-parchment-dark"
              aria-label="Search again"
            >
              <Search size={14} />
            </button>
          </div>
          <button
            onClick={onNoMatch}
            disabled={isLoading || isSaving}
            className="w-full py-1.5 text-sm border border-parchment-dark rounded text-archive-ink hover:bg-parchment-dark"
          >
            No match — skip this cell
          </button>
        </div>
      </div>
    </dialog>
  );
}
