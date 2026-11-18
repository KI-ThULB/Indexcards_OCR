import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Loader2, RefreshCcw, Scissors, ShieldCheck } from 'lucide-react';
import { toast } from 'sonner';
import { useWizardStore } from '../../store/wizardStore';
import type { ExtractionResult, ResultRow } from '../../store/wizardStore';
import type { BatchConfig } from '../../api/batchesApi';
import { useResultsQuery, resultWriteStatus, useRetryImageMutation, useRetryBatchMutation, useBatchConfigQuery } from '../../api/batchesApi';
import { SummaryBanner } from './SummaryBanner';
import { ResultsTable } from './ResultsTable';
import { useResultsExport } from './useResultsExport';
import { WizardNav } from '../../components/WizardNav';
import { ValidationFilterChips } from './ValidationFilterChips';
import type { ValidationFilter } from './ValidationFilterChips';

function exportFields(results: ResultRow[]) {
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
}

function hydrateResults(rawResults: ExtractionResult[], results: ResultRow[]): ResultRow[] {
  const existingEditsMap = new Map<string, Record<string, string>>(
    results.map((r) => [r.filename, r.editedData])
  );

  return rawResults.map((r) => {
    const data = r.data ?? {};
    const editedData = { ...existingEditsMap.get(r.filename), ...r.edited_data };
    const validation = r.validation && Object.fromEntries(
      Object.entries(r.validation).map(([field, outcome]) => {
        const storedValue = r.edited_data?.[field] ?? data[field] ?? '';
        const value = editedData[field] ?? data[field] ?? '';
        return [field, outcome?.reconciliation && value !== storedValue
          ? { ...outcome, reconciliation: null }
          : outcome];
      }),
    );
    return {
      filename: r.filename,
      status: r.success ? 'success' : 'failed',
      error: r.error ?? undefined,
      data,
      editedData,
      duration: r.duration,
      validation: validation ?? null,
      confidence: r.confidence ?? null,
      confidenceOverall: r.confidence_overall ?? null,
    };
  });
}

export const ResultsStep: React.FC = () => {
  const {
    batchId,
    batchRevision,
    results,
    processingState,
    setResults,
    setStep,
    setIsProcessing,
    resetWizard,
  } = useWizardStore();

  const { isProcessing } = processingState;
  const queryClient = useQueryClient();

  const { data: rawResults, isLoading, error } = useResultsQuery(batchId);

  const hydratedRef = useRef<typeof rawResults>(undefined);

  // Hydrate store from backend results on mount; merge existing edits
  useEffect(() => {
    if (!rawResults || hydratedRef.current === rawResults) return;
    hydratedRef.current = rawResults;

    const rows = hydrateResults(rawResults, results);
    setResults(rows, batchRevision);
  }, [rawResults, results, setResults, batchRevision]);

  // The batch's frozen group definitions drive the CSV's group columns, so an
  // export always matches the schema the batch was extracted with.
  useBatchConfigQuery(batchId);

  const fieldLabels = useMemo(() => exportFields(results), [results]);

  const failedCount = results.filter((r) => r.status === 'failed').length;
  const totalDuration = results.reduce((sum, r) => sum + r.duration, 0);

  // Validation filter state
  const [validationFilter, setValidationFilter] = useState<ValidationFilter>('all');

  // Per-row validation status counts for filter chips and SummaryBanner
  const validationCounts = useMemo(() => {
    const c = { all: results.length, invalid: 0, corrected: 0, valid: 0 };
    for (const r of results) {
      if (!r.validation) continue;
      const ss = Object.values(r.validation).map((v) => v?.status);
      if (ss.includes('invalid'))   c.invalid++;
      if (ss.includes('corrected')) c.corrected++;
      if (ss.length > 0 && ss.every((s) => s === 'valid')) c.valid++;
    }
    return c;
  }, [results]);

  const { downloadCSV, downloadJSON, downloadLIDO, downloadEAD, downloadDarwinCore, downloadDublinCore, downloadMARCXML, downloadMETSMODS } =
    useResultsExport(batchId ?? 'batch', () => {
      const current = useWizardStore.getState();
      if (!batchId || current.batchRevision !== batchRevision || current.batchId !== batchId) return null;
      const status = resultWriteStatus(queryClient, batchId);
      if (status !== 'ready') {
        toast.info(status === 'pending' ? 'Field changes are still being saved.' : 'Some changes could not be saved. Retry the changes or reload before exporting.');
        return null;
      }
      if (queryClient.getQueryState(['batchConfig', batchId])?.status === 'pending') {
        toast.info('Batch configuration is still loading.');
        return null;
      }
      const cached = queryClient.getQueryData<{ results: ExtractionResult[] }>(['results', batchId]);
      const rows = cached && hydratedRef.current !== cached.results
        ? hydrateResults(cached.results, current.results) : current.results;
      if (!rows.length) return null;
      const config = queryClient.getQueryData<BatchConfig>(['batchConfig', batchId]);
      return [rows, exportFields(rows), batchId, config?.field_groups, config?.authority_bindings];
    });

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
