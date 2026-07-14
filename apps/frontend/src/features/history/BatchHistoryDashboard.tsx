import React from 'react';
import { Loader2 } from 'lucide-react';
import { useBatchHistoryQuery } from '../../api/batchesApi';
import { BatchHistoryCard } from './BatchHistoryCard';

export const BatchHistoryDashboard: React.FC = () => {
  const { data: batches, isLoading, error } = useBatchHistoryQuery();

  // Sort batches newest-first
  const sortedBatches = batches
    ? [...batches].sort(
        (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
      )
    : [];

  return (
    <div className="max-w-6xl mx-auto space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-700">
      {/* Header */}
      <div className="flex flex-col gap-1">
        <h2 className="text-3xl font-serif text-archive-sepia">Batch Archive</h2>
        <p className="text-archive-ink/50 text-sm italic font-light">
          Browse, review, retry, or delete past extraction batches.
        </p>
      </div>

      {/* Loading state */}
      {isLoading && (
        <div className="flex flex-col items-center justify-center gap-4 py-24 text-archive-ink/50">
          <Loader2 className="w-8 h-8 animate-spin text-archive-sepia/60" />
          <p className="font-serif italic text-sm">Loading archive...</p>
        </div>
      )}

      {/* Error state */}
      {error && !isLoading && (
        <div className="flex flex-col items-center justify-center gap-4 py-24 text-archive-ink/50">
          <p className="font-serif italic text-sm text-red-600/70">
            Failed to load batch history. Please try refreshing.
          </p>
        </div>
      )}

      {/* Empty state */}
      {!isLoading && !error && sortedBatches.length === 0 && (
        <div className="flex flex-col items-center justify-center gap-4 py-24 text-archive-ink/40">
          <p className="font-serif italic text-sm">No batches in the archive yet.</p>
          <p className="text-xs text-archive-ink/30">Use <strong>New Batch</strong> in the sidebar to get started.</p>
        </div>
      )}

      {/* Batch grid */}
      {!isLoading && !error && sortedBatches.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {sortedBatches.map((batch) => (
            <BatchHistoryCard key={batch.batch_name} batch={batch} />
          ))}
        </div>
      )}
    </div>
  );
};
