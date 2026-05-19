import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Loader2, RefreshCcw, Scissors, ShieldCheck } from 'lucide-react';
import { toast } from 'sonner';
import { useWizardStore } from '../../store/wizardStore';
import type { ResultRow } from '../../store/wizardStore';
import { useResultsQuery, useRetryImageMutation, useRetryBatchMutation } from '../../api/batchesApi';
import { SummaryBanner } from './SummaryBanner';
import { ResultsTable } from './ResultsTable';
import { useResultsExport } from './useResultsExport';
import { WizardNav } from '../../components/WizardNav';
import { ValidationFilterChips } from './ValidationFilterChips';
import type { ValidationFilter } from './ValidationFilterChips';

export const ResultsStep: React.FC = () => {
  const {
    batchId,
    results,
    processingState,
    setResults,
    setStep,
    setIsProcessing,
    resetWizard,
  } = useWizardStore();

  const { isProcessing } = processingState;

  const { data: rawResults, isLoading, error } = useResultsQuery(batchId);

  const hydratedRef = useRef(false);

  // Hydrate store from backend results on mount; merge existing edits
  useEffect(() => {
    if (!rawResults || hydratedRef.current) return;
    hydratedRef.current = true;

    const existingEditsMap = new Map<string, Record<string, string>>(
      results.map((r) => [r.filename, r.editedData])
    );

    const rows: ResultRow[] = rawResults.map((r) => ({
      filename: r.filename,
      status: r.success ? 'success' : 'failed',
      error: r.error ?? undefined,
      data: r.data ?? {},
      editedData: r.edited_data
        ? { ...existingEditsMap.get(r.filename), ...r.edited_data }
        : existingEditsMap.get(r.filename) ?? {},
      duration: r.duration,
      validation: r.validation ?? null,   // backward compat with old batches that lack this key
    }));

    setResults(rows);
  }, [rawResults, results, setResults]);

  const fieldLabels = useMemo(() => {
    if (results.length === 0) return [];
    const seen = new Map<string, number>();
    results.forEach((r) => {
      // For multi-entry pages (Findmittel), field names live inside _entries — parse them first
      const entriesJson = r.data['_entries'];
      if (entriesJson) {
        try {
          const entries = JSON.parse(entriesJson) as Record<string, string>[];
          if (entries.length > 0) {
            Object.keys(entries[0]).forEach((k) => {
              if (!seen.has(k)) seen.set(k, seen.size);
            });
          }
        } catch { /* ignore malformed _entries */ }
      }
      Object.keys(r.data).forEach((k) => {
        if (!seen.has(k)) seen.set(k, seen.size);
      });
    });
    return Array.from(seen.entries())
      .sort((a, b) => a[1] - b[1])
      .map(([k]) => k)
      .filter((k) => !k.startsWith('_'));
  }, [results]);

  const failedCount = results.filter((r) => r.status === 'failed').length;
  const totalDuration = results.reduce((sum, r) => sum + r.duration, 0);

  // Validation filter state
  const [validationFilter, setValidationFilter] = useState<ValidationFilter>('all');

  // Per-row validation status counts for filter chips and SummaryBanner
  const validationCounts = useMemo(() => {
    const c = { all: results.length, invalid: 0, corrected: 0, valid: 0 };
    for (const r of results) {
      if (!r.validation) continue;
      const ss = Object.values(r.validation).map((v) => v.status);
      if (ss.includes('invalid'))   c.invalid++;
      if (ss.includes('corrected')) c.corrected++;
      if (ss.length > 0 && ss.every((s) => s === 'valid')) c.valid++;
    }
    return c;
  }, [results]);

  const { downloadCSV, downloadJSON, downloadLIDO, downloadEAD, downloadDarwinCore, downloadDublinCore, downloadMARCXML, downloadMETSMODS } =
    useResultsExport(results, fieldLabels, batchId ?? 'batch');

  const retryBatchMutation = useRetryBatchMutation();
  const retryImageMutation = useRetryImageMutation();
  const [retryingFilename, setRetryingFilename] = useState<string | null>(null);

  const handleRetryAllFailed = () => {
    if (!batchId) return;
    setIsProcessing(true);
    retryBatchMutation.mutate(batchId, {
      onSuccess: () => {
        setStep('processing');
      },
      onError: () => {
        toast.error('Failed to start retry.');
        setIsProcessing(false);
      },
    });
  };

  const handleRetryImage = (filename: string) => {
    if (!batchId) return;
    setRetryingFilename(filename);
    setIsProcessing(true);
    retryImageMutation.mutate(
      { batchName: batchId, filename },
      {
        onSuccess: () => {
          toast.success(`Retry started for ${filename}`);
          setRetryingFilename(null);
          setStep('processing');
        },
        onError: () => {
          toast.error(`Failed to retry ${filename}`);
          setRetryingFilename(null);
          setIsProcessing(false);
        },
      }
    );
  };

  const handleStartNewBatch = () => {
    resetWizard();
    // resetWizard sets step to 'upload' via initialState
  };

  // Loading state
  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 py-24 text-archive-ink/50">
        <Loader2 className="w-8 h-8 animate-spin text-archive-sepia/60" />
        <p className="font-serif italic text-sm">Loading archival results...</p>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 py-24 text-archive-ink/50">
        <p className="font-serif italic text-sm text-red-600/70">
          Failed to load results. Please try refreshing.
        </p>
      </div>
    );
  }

  // Empty state
  if (!isLoading && results.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 py-24 text-archive-ink/40">
        <p className="font-serif italic text-sm">No results found for this batch.</p>
      </div>
    );
  }

  return (
    <div className="flex-1 max-w-7xl mx-auto w-full space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-700">
      {/* Header */}
      <div className="flex flex-col gap-2">
        <h2 className="text-3xl font-serif text-archive-sepia">Archival Results</h2>
        {batchId && (
          <p className="text-archive-ink/60 italic font-light font-mono text-sm">{batchId}</p>
        )}
      </div>

      {/* Summary banner */}
      <SummaryBanner
        results={results}
        batchName={batchId ?? ''}
        totalDuration={totalDuration}
        onDownloadCSV={downloadCSV}
        onDownloadJSON={downloadJSON}
        onDownloadLIDO={downloadLIDO}
        onDownloadEAD={downloadEAD}
        onDownloadDarwinCore={downloadDarwinCore}
        onDownloadDublinCore={downloadDublinCore}
        onDownloadMARCXML={downloadMARCXML}
        onDownloadMETSMODS={downloadMETSMODS}
        onRetryAllFailed={handleRetryAllFailed}
        failedCount={failedCount}
        invalidCount={validationCounts.invalid}
        correctedCount={validationCounts.corrected}
        isProcessing={isProcessing}
      />

      {/* Validation filter chips (only shown when any row has validation data) */}
      {(validationCounts.invalid > 0 || validationCounts.corrected > 0 || validationCounts.valid > 0) && (
        <div className="flex items-center gap-3 flex-wrap">
          <ValidationFilterChips
            value={validationFilter}
            onChange={setValidationFilter}
            counts={validationCounts}
          />
          <button
            onClick={() => setStep('verify')}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded
                       bg-archive-700 text-parchment-paper hover:bg-archive-900 transition-colors
                       disabled:opacity-50 disabled:cursor-not-allowed"
            disabled={!results.length}
            title="Open verification cockpit"
          >
            <ShieldCheck className="w-4 h-4" />
            Verify cards
          </button>
          <button
            onClick={() => setStep('clean')}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded
                       bg-archive-100 text-archive-800 hover:bg-archive-200 transition-colors
                       border border-archive-300 disabled:opacity-50 disabled:cursor-not-allowed"
            disabled={!results.length}
            title="Open cleaning stage"
          >
            <Scissors className="w-4 h-4" />
            Clean columns
          </button>
        </div>
      )}

      {/* Verify cards action row (shown when no validation data exists — plain batches still get cockpit) */}
      {validationCounts.invalid === 0 && validationCounts.corrected === 0 && validationCounts.valid === 0 && (
        <div className="flex items-center gap-3">
          <button
            onClick={() => setStep('verify')}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded
                       bg-archive-700 text-parchment-paper hover:bg-archive-900 transition-colors
                       disabled:opacity-50 disabled:cursor-not-allowed"
            disabled={!results.length}
            title="Open verification cockpit"
          >
            <ShieldCheck className="w-4 h-4" />
            Verify cards
          </button>
          <button
            onClick={() => setStep('clean')}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded
                       bg-archive-100 text-archive-800 hover:bg-archive-200 transition-colors
                       border border-archive-300 disabled:opacity-50 disabled:cursor-not-allowed"
            disabled={!results.length}
            title="Open cleaning stage"
          >
            <Scissors className="w-4 h-4" />
            Clean columns
          </button>
        </div>
      )}

      {/* Results table */}
      <div className="parchment-shadow border border-parchment-dark rounded-lg overflow-hidden">
        <ResultsTable
          results={results}
          fields={fieldLabels}
          batchName={batchId ?? ''}
          onRetryImage={handleRetryImage}
          isProcessing={isProcessing}
          retryingFilename={retryingFilename}
          validationFilter={validationFilter}
        />
      </div>

      <WizardNav
        next={{
          label: 'Start New Batch',
          onClick: handleStartNewBatch,
          icon: <RefreshCcw className="w-5 h-5" />,
        }}
      />
    </div>
  );
};
