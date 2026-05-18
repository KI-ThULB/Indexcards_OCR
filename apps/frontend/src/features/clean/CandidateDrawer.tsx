import { useState, useEffect } from 'react';
import { X, Link2, Search, AlertCircle, Loader2 } from 'lucide-react';
import type { ReconcileCandidate } from '../../api/batchesApi';

interface CandidateDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  cellValue: string;         // current cell value (original query)
  authority: string;         // authority type label (for header display)
  candidates: ReconcileCandidate[];
  isLoading: boolean;
  error: string | null;      // "API error — retry?" or null
  onPick: (candidate: ReconcileCandidate) => void;
  onNoMatch: () => void;
  onSearchAgain: (refinedQuery: string) => void;
}

export function CandidateDrawer({
  isOpen,
  onClose,
  cellValue,
  authority,
  candidates,
  isLoading,
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

  // Close on Escape key
  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-x-0 bottom-0 z-50 flex justify-center pb-4 px-4"
      role="dialog"
      aria-modal="true"
      aria-label={`Reconcile: ${cellValue}`}
    >
      <div className="w-full max-w-lg bg-parchment-paper border border-archive-300 rounded-xl shadow-xl flex flex-col max-h-[60vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-archive-200 shrink-0">
          <div className="flex items-center gap-2 min-w-0">
            <Link2 size={14} className="text-archive-500 shrink-0" />
            <span className="text-sm font-semibold text-archive-800 truncate">
              Reconcile: <span className="text-archive-600">{cellValue}</span>
            </span>
            <span className="text-xs text-archive-500 ml-1 shrink-0">via {authority}</span>
          </div>
          <button
            onClick={onClose}
            className="text-archive-500 hover:text-archive-800 shrink-0 ml-2"
            aria-label="Close candidate drawer"
          >
            <X size={16} />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-3">
          {isLoading && (
            <div className="flex items-center gap-2 text-sm text-archive-600 py-4 justify-center">
              <Loader2 size={16} className="animate-spin" />
              <span>Querying {authority}...</span>
            </div>
          )}
          {error && !isLoading && (
            <div className="flex items-center gap-2 text-sm text-red-700 bg-red-50 rounded p-3 mb-3">
              <AlertCircle size={14} className="shrink-0" />
              <span>{error}</span>
            </div>
          )}
          {!isLoading && !error && candidates.length === 0 && (
            <p className="text-sm text-archive-500 py-4 text-center">No candidates found.</p>
          )}
          {!isLoading &&
            candidates.map((c, i) => (
              <div
                key={i}
                className="flex items-start gap-3 py-2.5 border-b border-archive-100 last:border-0"
              >
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-archive-800">{c.label}</p>
                  {c.description && (
                    <p className="text-xs text-archive-500 mt-0.5 truncate">{c.description}</p>
                  )}
                  <a
                    href={c.uri}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-blue-600 hover:underline truncate block mt-0.5"
                  >
                    {c.uri}
                  </a>
                </div>
                <button
                  onClick={() => onPick(c)}
                  className="shrink-0 px-2.5 py-1 text-xs bg-archive-700 text-parchment-paper rounded hover:bg-archive-900 whitespace-nowrap"
                >
                  Pick this
                </button>
              </div>
            ))}
        </div>

        {/* Footer: Search again + No match */}
        <div className="p-3 border-t border-archive-200 flex flex-col gap-2 shrink-0">
          <div className="flex gap-2">
            <input
              type="text"
              value={refinedQuery}
              onChange={(e) => setRefinedQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') onSearchAgain(refinedQuery);
              }}
              placeholder="Search again with different query..."
              className="flex-1 border border-archive-300 rounded px-2 py-1.5 text-sm bg-parchment-paper text-archive-800 focus:outline-none focus:ring-1 focus:ring-archive-400"
            />
            <button
              onClick={() => onSearchAgain(refinedQuery)}
              className="px-2.5 py-1.5 border border-archive-300 rounded text-archive-700 hover:bg-archive-50"
              aria-label="Search again"
            >
              <Search size={14} />
            </button>
          </div>
          <button
            onClick={onNoMatch}
            className="w-full py-1.5 text-sm border border-archive-300 rounded text-archive-600 hover:bg-archive-50"
          >
            No match — skip this cell
          </button>
        </div>
      </div>
    </div>
  );
}
