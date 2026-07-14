import { useState, useEffect } from 'react';
import { Sparkles } from 'lucide-react';
import type { ClusterGroup } from './fingerprint';

interface ClusterPickerProps {
  clusters: ClusterGroup[];
  onApply: (fingerprint: string, canonical: string) => void;  // wired in 10-04
  onSkip: (fingerprint: string) => void;
  isLoading?: boolean;  // while clusters are being computed
  /** Reset token — when this changes (e.g. column switch), skipped state is cleared */
  resetKey?: string;
}

/**
 * Table UI for fingerprint clusters.
 * One row per cluster. Curator reviews variants, optionally edits the canonical value,
 * then clicks Apply (merges all variants → canonical) or Skip (ignores this cluster).
 * Skipped clusters stay hidden for the session; skipped state resets on resetKey change.
 */
export function ClusterPicker({
  clusters,
  onApply,
  onSkip,
  isLoading = false,
  resetKey,
}: ClusterPickerProps) {
  // Per-cluster canonical value edits before Apply
  const [editedCanonicals, setEditedCanonicals] = useState<Record<string, string>>({});
  // Skipped clusters hidden for the session
  const [skippedFingerprints, setSkippedFingerprints] = useState<Set<string>>(new Set());

  // Reset skipped state when resetKey changes (e.g. user switches to a different column)
  useEffect(() => {
    setSkippedFingerprints(new Set());
    setEditedCanonicals({});
  }, [resetKey]);

  const setEditedCanonical = (fingerprint: string, value: string) => {
    setEditedCanonicals(prev => ({ ...prev, [fingerprint]: value }));
  };

  const handleApply = (fingerprint: string, canonical: string) => {
    onApply(fingerprint, canonical);
    // Remove from skipped in case it was previously skipped and re-shown
    setSkippedFingerprints(prev => {
      const next = new Set(prev);
      next.delete(fingerprint);
      return next;
    });
    // Clear edited canonical for this cluster
    setEditedCanonicals(prev => {
      const next = { ...prev };
      delete next[fingerprint];
      return next;
    });
  };

  const handleSkip = (fingerprint: string) => {
    onSkip(fingerprint);
    setSkippedFingerprints(prev => new Set(prev).add(fingerprint));
  };

  const visibleClusters = clusters.filter(c => !skippedFingerprints.has(c.fingerprint));

  return (
    <div className="border border-archive-200 rounded-lg mx-4 mt-4 overflow-hidden">
      {/* Header */}
      <div className="px-4 py-2 bg-archive-50 border-b border-archive-200 flex items-center gap-2">
        <Sparkles size={14} className="text-archive-500" />
        <span className="text-sm font-medium text-archive-800">Cluster Suggestions</span>
        {!isLoading && (
          <span className="text-xs text-archive-500">
            {visibleClusters.length} near-duplicate group{visibleClusters.length !== 1 ? 's' : ''} found
          </span>
        )}
      </div>

      {/* Loading state */}
      {isLoading && (
        <div className="px-4 py-6 text-sm text-archive-400 text-center">
          Computing clusters…
        </div>
      )}

      {/* Empty state */}
      {!isLoading && visibleClusters.length === 0 && (
        <p className="text-sm text-archive-400 text-center py-6">
          No near-duplicate clusters found for this column.
        </p>
      )}

      {/* Cluster table */}
      {!isLoading && visibleClusters.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-archive-100 bg-white">
                <th className="text-left px-4 py-2 text-xs font-medium text-archive-500 w-auto">Variants</th>
                <th className="text-right px-3 py-2 text-xs font-medium text-archive-500 w-16">Rows</th>
                <th className="text-left px-3 py-2 text-xs font-medium text-archive-500 w-48">Merge to</th>
                <th className="text-left px-3 py-2 text-xs font-medium text-archive-500 w-24">Actions</th>
              </tr>
            </thead>
            <tbody>
              {visibleClusters.map((cluster) => {
                const MAX_SHOWN = 4;
                const shownValues = cluster.values.slice(0, MAX_SHOWN);
                const hiddenCount = cluster.values.length - MAX_SHOWN;
                const canonicalValue = editedCanonicals[cluster.fingerprint] ?? cluster.canonical;

                return (
                  <tr
                    key={cluster.fingerprint}
                    className="border-b border-archive-50 hover:bg-archive-25 transition-colors"
                  >
                    {/* Variants column */}
                    <td className="px-4 py-2">
                      <div className="flex flex-wrap gap-1">
                        {shownValues.map(v => (
                          <span
                            key={v}
                            className="text-xs bg-archive-100 px-1 rounded text-archive-700"
                          >
                            {v}
                          </span>
                        ))}
                        {hiddenCount > 0 && (
                          <span className="text-xs text-archive-400 italic">
                            +{hiddenCount} more
                          </span>
                        )}
                      </div>
                    </td>

                    {/* Row count column */}
                    <td className="px-3 py-2 text-right text-sm tabular-nums text-archive-700">
                      {cluster.rowCount}
                    </td>

                    {/* Editable canonical input */}
                    <td className="px-3 py-2">
                      <input
                        type="text"
                        value={canonicalValue}
                        onChange={(e) => setEditedCanonical(cluster.fingerprint, e.target.value)}
                        className="w-full text-sm border border-archive-300 rounded px-1.5 py-0.5 bg-white text-archive-800 focus:outline-none focus:ring-1 focus:ring-archive-400"
                      />
                    </td>

                    {/* Actions column */}
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-1.5">
                        <button
                          onClick={() => handleApply(cluster.fingerprint, canonicalValue)}
                          className="px-2 py-0.5 text-xs rounded bg-archive-700 text-parchment-paper hover:bg-archive-900 transition-colors"
                        >
                          Apply
                        </button>
                        <button
                          onClick={() => handleSkip(cluster.fingerprint)}
                          className="px-2 py-0.5 text-xs rounded border border-archive-300 text-archive-600 hover:bg-archive-50 transition-colors"
                        >
                          Skip
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
