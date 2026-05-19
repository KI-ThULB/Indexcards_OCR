import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ArrowLeft, Loader2, Scissors } from 'lucide-react';
import axios from 'axios';
import { useWizardStore } from '../../store/wizardStore';
import type { ResultRow } from '../../store/wizardStore';
import { useResultsQuery } from '../../api/batchesApi';
import { CockpitLayout } from './CockpitLayout';
import { ImagePane } from './ImagePane';
import { Filmstrip } from './Filmstrip';
import type { ValidationFilter } from './Filmstrip';
import { FieldsPane } from './FieldsPane';
import { useVerifyKeyboard } from './useVerifyKeyboard';

export const VerifyStep: React.FC = () => {
  const batchId = useWizardStore((s) => s.batchId);
  const results = useWizardStore((s) => s.results);
  const setResults = useWizardStore((s) => s.setResults);
  const setStep = useWizardStore((s) => s.setStep);
  const acceptCorrectorProposal = useWizardStore((s) => s.acceptCorrectorProposal);

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
      editedData: r.edited_data
        ? { ...existingEditsMap.get(r.filename), ...r.edited_data }
        : existingEditsMap.get(r.filename) ?? {},
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

  // Clamp active index when filtered cards length changes (filter change or card count change)
  useEffect(() => {
    setActiveCardIndex((prev) => Math.min(prev, Math.max(0, filteredCards.length - 1)));
  }, [filteredCards.length]);

  // Batch-level progress: how many cards have at least one verified field
  const verifiedCardCount = useMemo(
    () =>
      results.filter(
        (r) =>
          r.validation &&
          Object.values(r.validation).some((v) => v.status === 'verified')
      ).length,
    [results]
  );

  // ── Keyboard shortcut handlers ──────────────────────────────────────────────

  const handleNextCard = useCallback(() => {
    setActiveCardIndex((i) => Math.min(i + 1, filteredCards.length - 1));
  }, [filteredCards.length]);

  const handlePrevCard = useCallback(() => {
    setActiveCardIndex((i) => Math.max(i - 1, 0));
  }, []);

  const handleMarkVerified = useCallback(() => {
    // V shortcut: flip the FIRST non-verified field of the active card to 'verified'.
    // The act of pressing V marks the next-pending field, giving one-keystroke progression
    // through a card's remaining fields without requiring a text edit.
    if (!activeCard) return;
    const firstPending = Object.entries(activeCard.validation ?? {}).find(
      ([, v]) => v.status !== 'verified'
    );
    if (firstPending) {
      const [field] = firstPending;
      useWizardStore.setState((state) => ({
        results: state.results.map((r) => {
          if (r.filename !== activeCard.filename) return r;
          const newValidation = r.validation ? { ...r.validation } : {};
          newValidation[field] = {
            ...(newValidation[field] ?? { status: 'valid' }),
            status: 'verified',
          };
          return { ...r, validation: newValidation };
        }),
      }));
      // Fire PATCH for status-only update (no value change)
      axios
        .patch(
          `/api/v1/batches/${batchId}/results/${encodeURIComponent(activeCard.filename)}`,
          { field, value: null, validation_status: 'verified' }
        )
        .catch((err) => console.warn('[VerifyStep] PATCH failed for V shortcut', err));
    }
  }, [activeCard, batchId]);

  const handleAcceptProposal = useCallback(() => {
    if (!activeCard) return;
    // Accept the first corrected proposal on the active card
    const firstCorrected = Object.entries(activeCard.validation ?? {}).find(
      ([, v]) => v.status === 'corrected' && v.corrector_proposal != null
    );
    if (firstCorrected) {
      const [field] = firstCorrected;
      acceptCorrectorProposal(activeCard.filename, field);
    }
  }, [activeCard, acceptCorrectorProposal]);

  useVerifyKeyboard(
    {
      onNextCard: handleNextCard,
      onPrevCard: handlePrevCard,
      onMarkVerified: handleMarkVerified,
      onAcceptProposal: handleAcceptProposal,
    },
    true // always enabled while VerifyStep is mounted
  );

  // ── Image URL ───────────────────────────────────────────────────────────────

  const imageUrl =
    activeCard && batchId
      ? `/batches-static/${batchId}/${activeCard.filename}`
      : '';

  // ── Loading / error / empty states ─────────────────────────────────────────

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 py-24 text-archive-ink/50">
        <Loader2 className="w-8 h-8 animate-spin text-archive-sepia/60" />
        <p className="font-serif italic text-sm">Loading verification cockpit...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 py-24 text-archive-ink/50">
        <p className="font-serif italic text-sm text-red-600/70">
          Failed to load batch results. Please try refreshing.
        </p>
      </div>
    );
  }

  if (!isLoading && results.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 py-24 text-archive-ink/40">
        <p className="font-serif italic text-sm">No results found for this batch.</p>
      </div>
    );
  }

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col h-screen min-h-0 overflow-hidden bg-parchment">
      {/* Cockpit header row: back button + progress indicator */}
      <div className="flex items-center gap-3 px-3 py-1.5 border-b border-archive-200 bg-parchment-light shrink-0">
        <button
          onClick={() => setStep('results')}
          className="flex items-center gap-1 text-sm text-archive-600 hover:text-archive-900 px-2 py-1 rounded transition-colors"
          title="Return to Results"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Results
        </button>
        <button
          onClick={() => setStep('clean')}
          className="flex items-center gap-1 text-sm text-archive-600 hover:text-archive-900 px-2 py-1 rounded transition-colors"
          title="Open cleaning stage"
        >
          <Scissors className="w-4 h-4" />
          Clean columns
        </button>
        {/* Auto-save note: all edits fire debounced PATCHes (300ms) from FieldsPane.
            Navigating back to Results does not require an explicit flush — the
            debounce window closes naturally before the Results view re-renders. */}
        <span className="text-xs text-archive-500 ml-auto">
          {verifiedCardCount} of {results.length} cards touched
        </span>
      </div>

      {/* Main cockpit area — takes all available vertical space above filmstrip */}
      <div className="flex-1 min-h-0">
        <CockpitLayout
          left={<ImagePane imageUrl={imageUrl} />}
          right={
            activeCard ? (
              <FieldsPane
                card={activeCard}
                batchId={batchId!}
                onFieldVerified={() => {
                  // Callback is informational — filmstrip status dots re-derive from
                  // Zustand results state automatically on next render cycle.
                }}
              />
            ) : (
              <div className="p-4 text-archive-ink/60 text-sm font-serif italic">
                No card selected.
              </div>
            )
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
        onCardSelect={(idx) => setActiveCardIndex(idx)}
        batchId={batchId ?? ''}
      />
    </div>
  );
};
