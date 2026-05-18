import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { useWizardStore } from '../../store/wizardStore';
import type { ResultRow } from '../../store/wizardStore';
import { useResultsQuery } from '../../api/batchesApi';
import { CockpitLayout } from './CockpitLayout';
import { ImagePane } from './ImagePane';
import { Filmstrip } from './Filmstrip';
import type { ValidationFilter } from './Filmstrip';

export const VerifyStep: React.FC = () => {
  const batchId = useWizardStore((s) => s.batchId);
  const results = useWizardStore((s) => s.results);
  const setResults = useWizardStore((s) => s.setResults);

  const { data: rawResults, isLoading, error } = useResultsQuery(batchId);

  const hydratedRef = useRef(false);

  // Hydrate store from backend results on mount — same pattern as ResultsStep
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
      editedData: existingEditsMap.get(r.filename) ?? {},
      duration: r.duration,
      validation: r.validation ?? null,
    }));

    setResults(rows);
  }, [rawResults, results, setResults]);

  // Filter state — default 'invalid' per CONTEXT.md: start with cards that have issues
  const [filter, setFilter] = useState<ValidationFilter>('invalid');
  const [activeCardIndex, setActiveCardIndex] = useState(0);

  // Derive filtered card list
  const filteredCards = useMemo(() => {
    if (filter === 'all') return results;
    return results.filter((r) => {
      if (!r.validation) return false;
      const statuses = Object.values(r.validation).map((v) => v.status);
      if (filter === 'invalid') return statuses.includes('invalid');
      if (filter === 'corrected') return statuses.includes('corrected');
      if (filter === 'valid') return statuses.length > 0 && statuses.every((s) => s === 'valid');
      if (filter === 'verified') return statuses.includes('verified');
      return false;
    });
  }, [results, filter]);

  // Active card: from filtered list, fallback to first card from all results
  const activeCard: ResultRow | null =
    filteredCards[activeCardIndex] ?? results[0] ?? null;

  // Reset active index when filter changes
  useEffect(() => {
    setActiveCardIndex(0);
  }, [filter]);

  // Clamp active index when filtered cards length changes
  useEffect(() => {
    if (activeCardIndex >= filteredCards.length && filteredCards.length > 0) {
      setActiveCardIndex(filteredCards.length - 1);
    }
  }, [filteredCards.length, activeCardIndex]);

  const imageUrl = activeCard && batchId
    ? `/batches-static/${batchId}/${activeCard.filename}`
    : '';

  // Loading state
  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 py-24 text-archive-ink/50">
        <Loader2 className="w-8 h-8 animate-spin text-archive-sepia/60" />
        <p className="font-serif italic text-sm">Loading verification cockpit...</p>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 py-24 text-archive-ink/50">
        <p className="font-serif italic text-sm text-red-600/70">
          Failed to load batch results. Please try refreshing.
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
    <div className="flex flex-col h-screen min-h-0 overflow-hidden bg-parchment">
      {/* Main cockpit area — takes all available vertical space above filmstrip */}
      <div className="flex-1 min-h-0">
        <CockpitLayout
          left={<ImagePane imageUrl={imageUrl} />}
          right={
            <div className="p-4 text-archive-ink/60 text-sm font-serif italic">
              Field pane (Plan 09-03)
            </div>
          }
        />
      </div>

      {/* Filmstrip — fixed height bar at bottom */}
      <Filmstrip
        cards={results}
        activeIndex={activeCardIndex}
        filter={filter}
        onFilterChange={(f) => {
          setFilter(f);
          setActiveCardIndex(0);
        }}
        onCardSelect={setActiveCardIndex}
        batchId={batchId ?? ''}
      />
    </div>
  );
};
