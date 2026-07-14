import React, { useCallback, useEffect, useRef } from 'react';
import { AlertTriangle, X, ArrowLeft } from 'lucide-react';
import { toast } from 'sonner';
import { useWizardStore } from '../../store/wizardStore';
import type { BatchProgress } from '../../store/wizardStore';
import { useProcessingWebSocket } from './useProcessingWebSocket';
import { ProgressBar } from './ProgressBar';
import { LiveFeed } from './LiveFeed';
import { cancelBatch } from '../../api/batchesApi';

export const ProcessingStep: React.FC = () => {
  const {
    batchId,
    processingState,
    setStep,
    appendLiveFeedItem,
    setLastProgress,
    incrementConsecutiveFailures,
    resetConsecutiveFailures,
    setCancelled,
    setIsProcessing,
    resetProcessing,
  } = useWizardStore();

  const { consecutiveFailures, liveFeedItems, lastProgress, isCancelled, isProcessing } =
    processingState;

  // Track whether we've already initiated a reset (to avoid double-reset on re-renders)
  const initializedRef = useRef(false);

  useEffect(() => {
    if (!initializedRef.current) {
      initializedRef.current = true;
      // Only reset if there's no existing progress (handles page refresh mid-processing)
      if (!processingState.lastProgress) {
        resetProcessing();
      }
      setIsProcessing(true);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const navigateToResultsRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleProgress = useCallback(
    (progress: BatchProgress) => {
      setLastProgress(progress);

      if (progress.last_result) {
        appendLiveFeedItem(progress.last_result);
        if (progress.last_result.success === false) {
          incrementConsecutiveFailures();
        } else {
          resetConsecutiveFailures();
        }
      }

      if (progress.status === 'completed' || progress.status === 'cancelled') {
        setIsProcessing(false);
        // Auto-navigate to results after 2s
        if (!navigateToResultsRef.current) {
          navigateToResultsRef.current = setTimeout(() => {
            setStep('results');
          }, 2000);
        }
      }

      // Batch-level failure broadcast from backend
      if (progress.status === 'failed') {
        setIsProcessing(false);
      }
    },
    [
      setLastProgress,
      appendLiveFeedItem,
      incrementConsecutiveFailures,
      resetConsecutiveFailures,
      setIsProcessing,
      setStep,
    ]
  );

  const { close: closeWebSocket } = useProcessingWebSocket(batchId, handleProgress);

  // Cleanup timer on unmount
  useEffect(() => {
    return () => {
      if (navigateToResultsRef.current) {
        clearTimeout(navigateToResultsRef.current);
      }
    };
  }, []);

  // Catastrophic failure detection: 3 consecutive failures OR batch-level "failed" status
  const isBatchFailed = lastProgress?.status === 'failed';
  const isCatastrophicFailure = consecutiveFailures >= 3 || isBatchFailed;

  // Extract the most relevant error message for display
  const errorDetail =
    lastProgress?.error ||
    liveFeedItems.findLast((item) => item.error)?.error ||
    null;

  useEffect(() => {
    if (isCatastrophicFailure && isProcessing) {
      closeWebSocket();
      setIsProcessing(false);
      if (batchId) {
        cancelBatch(batchId).catch(() => {
          // Best-effort cancel — ignore errors
        });
      }
    }
  }, [isCatastrophicFailure, isProcessing, closeWebSocket, setIsProcessing, batchId]);

  const handleCancel = async () => {
    if (!batchId) return;
    setCancelled(true);
    toast.info('Cancelling... finishing current image');
    try {
      await cancelBatch(batchId);
    } catch {
      // WS will deliver cancelled status; ignore cancel API errors
    }
  };

  const handleReturnToConfigure = () => {
    closeWebSocket();
    setStep('configure');
  };

  // Catastrophic failure screen
  if (isCatastrophicFailure) {
    return (
      <div className="max-w-2xl mx-auto animate-in fade-in slide-in-from-bottom-4 duration-700">
        <div className="bg-parchment-light/30 border border-red-500/30 rounded-lg p-8 space-y-6 parchment-shadow">
          <div className="flex items-start gap-4">
            <AlertTriangle className="w-8 h-8 text-red-500/70 flex-shrink-0 mt-1" />
            <div className="space-y-2">
              <h2 className="text-2xl font-serif text-archive-sepia">Processing Halted</h2>
              <p className="text-archive-ink/60 font-serif italic">
                {isBatchFailed
                  ? 'The backend reported a processing failure.'
                  : 'Processing stopped after 3 consecutive failures.'}
              </p>
            </div>
          </div>

          {errorDetail && (
            <div className="bg-red-50/30 border border-red-500/20 rounded p-4">
              <h3 className="text-xs uppercase tracking-widest text-red-700/50 font-semibold mb-2">
                Error Detail
              </h3>
              <p className="text-sm text-red-800/80 font-mono break-words">{errorDetail}</p>
            </div>
          )}

          <div className="space-y-2 bg-archive-ink/5 border border-archive-ink/10 rounded p-4">
            <h3 className="text-xs uppercase tracking-widest text-archive-ink/40 font-semibold">
              Troubleshooting
            </h3>
            <ul className="space-y-2 text-sm text-archive-ink/70 font-serif">
              <li className="flex items-start gap-2">
                <span className="text-archive-sepia mt-0.5">•</span>
                Check your <code className="font-mono text-xs bg-parchment-dark/30 px-1 rounded">OPENROUTER_API_KEY</code> in the <code className="font-mono text-xs bg-parchment-dark/30 px-1 rounded">.env</code> file
              </li>
              <li className="flex items-start gap-2">
                <span className="text-archive-sepia mt-0.5">•</span>
                Verify your internet connection is active
              </li>
              <li className="flex items-start gap-2">
                <span className="text-archive-sepia mt-0.5">•</span>
                Check the backend logs for detailed error messages
              </li>
            </ul>
          </div>

          <button
            onClick={handleReturnToConfigure}
            className="flex items-center gap-2 px-6 py-3 rounded font-serif text-lg text-archive-ink/60 hover:text-archive-sepia hover:bg-parchment-dark/10 transition-all"
          >
            <ArrowLeft className="w-5 h-5" />
            Return to Configure
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-700">
      {/* Header */}
      <div className="flex flex-col gap-2">
        <h2 className="text-3xl font-serif text-archive-sepia">Processing Collection</h2>
        {batchId && (
          <p className="text-archive-ink/60 italic font-light font-mono text-sm">
            {batchId}
          </p>
        )}
      </div>

      {/* Progress area */}
      <div className="bg-parchment-light/30 border border-parchment-dark/50 p-6 rounded-lg parchment-shadow space-y-6">
        <div className="flex flex-col gap-1">
          <label className="text-xs uppercase tracking-widest text-archive-ink/40 font-semibold">
            Extraction Progress
          </label>
        </div>

        <ProgressBar progress={lastProgress} />

        {/* Cancel button — right-aligned, subtle destructive */}
        {isProcessing && !isCancelled && (
          <div className="flex justify-end">
            <button
              onClick={handleCancel}
              className="flex items-center gap-2 px-4 py-2 rounded font-serif text-sm text-archive-ink/50 border border-archive-ink/20 hover:border-red-500/40 hover:text-red-600/70 hover:bg-red-50/10 transition-all"
            >
              <X className="w-4 h-4" />
              Cancel Processing
            </button>
          </div>
        )}

        {isCancelled && (
          <p className="text-sm text-archive-ink/50 italic text-center">
            Cancellation requested — finishing current image...
          </p>
        )}

        {!isProcessing && lastProgress?.status === 'completed' && (
          <p className="text-sm text-green-700/70 italic text-center font-serif">
            Complete! Navigating to results...
          </p>
        )}

        {!isProcessing && lastProgress?.status === 'cancelled' && (
          <p className="text-sm text-archive-ink/50 italic text-center font-serif">
            Processing cancelled. Navigating to results with partial data...
          </p>
        )}
      </div>

      {/* Live feed */}
      <div className="space-y-3">
        <label className="text-xs uppercase tracking-widest text-archive-ink/40 font-semibold">
          Live Extraction Feed
        </label>
        <LiveFeed items={liveFeedItems} />
      </div>
    </div>
  );
};
