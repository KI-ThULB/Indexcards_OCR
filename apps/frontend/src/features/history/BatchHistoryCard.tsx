import React from 'react';
import { Eye, RotateCcw, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import type { BatchHistoryItem } from '../../api/batchesApi';
import { useDeleteBatchMutation } from '../../api/batchesApi';
import { retryBatch } from '../../api/batchesApi';
import { useWizardStore } from '../../store/wizardStore';

interface BatchHistoryCardProps {
  batch: BatchHistoryItem;
}

const statusStyles: Record<string, string> = {
  completed: 'bg-green-100 text-green-800 border-green-200',
  uploaded: 'bg-blue-100 text-blue-800 border-blue-200',
  running: 'bg-yellow-100 text-yellow-800 border-yellow-200',
  failed: 'bg-red-100 text-red-800 border-red-200',
  cancelled: 'bg-gray-100 text-gray-600 border-gray-200',
};

const formatDate = (isoString: string): string => {
  try {
    return new Date(isoString).toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  } catch {
    return isoString;
  }
};

export const BatchHistoryCard: React.FC<BatchHistoryCardProps> = ({ batch }) => {
  const { loadBatchForReview, setStep, setBatchId, setView } = useWizardStore();
  const deleteMutation = useDeleteBatchMutation();

  const statusClass = statusStyles[batch.status] ?? 'bg-gray-100 text-gray-600 border-gray-200';
  const canReview = batch.status === 'completed' || batch.status === 'uploaded';

  const handleReview = () => {
    loadBatchForReview(batch.batch_name);
  };

  const handleRetry = async () => {
    try {
      await retryBatch(batch.batch_name);
      toast.success(`Retry started for "${batch.custom_name}"`);
      setBatchId(batch.batch_name);
      setStep('processing');
      setView('wizard');
    } catch {
      toast.error('Failed to start retry.');
    }
  };

  const handleDelete = () => {
    toast(`Delete batch "${batch.custom_name}"?`, {
      action: {
        label: 'Delete',
        onClick: () => {
          deleteMutation.mutate(batch.batch_name);
        },
      },
      cancel: {
        label: 'Cancel',
        onClick: () => {},
      },
    });
  };

  return (
    <div className="bg-parchment-light/30 border border-parchment-dark/50 rounded-lg p-5 flex flex-col gap-3 hover:border-archive-sepia/30 hover:shadow-sm transition-all duration-200">
      {/* Top row: name + status */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-col gap-0.5">
          <h3 className="font-serif text-lg text-archive-ink leading-tight">{batch.custom_name}</h3>
          <span className="font-mono text-[10px] text-archive-ink/40 leading-tight truncate" title={batch.batch_name}>{batch.batch_name}</span>
        </div>
        <span
          className={`flex-shrink-0 text-xs font-medium px-2 py-0.5 rounded-full border ${statusClass}`}
        >
          {batch.status}
        </span>
      </div>

      {/* Details row */}
      <div className="flex flex-wrap gap-3 text-xs text-archive-ink/60 font-mono">
        <span>{formatDate(batch.created_at)}</span>
        <span>&bull;</span>
        <span>{batch.files_count} files</span>
        <span>&bull;</span>
        <span>{batch.fields.length} fields</span>
        {batch.has_errors && (
          <>
            <span>&bull;</span>
            <span className="text-red-600 font-medium">{batch.error_count} errors</span>
          </>
        )}
      </div>

      {/* Action buttons */}
      <div className="flex items-center gap-2 pt-1 border-t border-parchment-dark/20">
        {canReview && (
          <button
            onClick={handleReview}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium border border-parchment-dark/40 rounded text-archive-ink/70 hover:text-archive-sepia hover:border-archive-sepia/50 hover:bg-parchment-dark/10 transition-all"
          >
            <Eye size={13} />
            Review Results
          </button>
        )}

        {batch.has_errors && (
          <button
            onClick={handleRetry}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium border border-parchment-dark/40 rounded text-archive-ink/70 hover:text-amber-700 hover:border-amber-400/50 hover:bg-amber-50/20 transition-all"
          >
            <RotateCcw size={13} />
            Retry
          </button>
        )}

        <button
          onClick={handleDelete}
          disabled={deleteMutation.isPending}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium border border-parchment-dark/40 rounded text-archive-ink/70 hover:text-red-600 hover:border-red-300 hover:bg-red-50/20 transition-all ml-auto disabled:opacity-50"
        >
          <Trash2 size={13} />
          Delete
        </button>
      </div>
    </div>
  );
};
