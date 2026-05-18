import React, { useEffect, useRef } from 'react';
import type { ResultRow } from '../../store/wizardStore';

export type ValidationFilter = 'all' | 'invalid' | 'corrected' | 'valid' | 'verified';

interface FilmstripProps {
  cards: ResultRow[];           // All results (unfiltered)
  activeIndex: number;          // Index into filtered cards
  filter: ValidationFilter;     // Current filter chip value
  onFilterChange: (f: ValidationFilter) => void;
  onCardSelect: (index: number) => void;  // Index into filtered array
  batchId: string;
}

type FilterChip = { key: ValidationFilter; label: string };

const FILTER_CHIPS: FilterChip[] = [
  { key: 'all',       label: 'All' },
  { key: 'invalid',   label: 'Invalid' },
  { key: 'corrected', label: 'Corrected' },
  { key: 'valid',     label: 'Valid' },
  { key: 'verified',  label: 'Verified' },
];

/** Returns the worst-case validation status dot color for a card */
function getStatusDotClass(card: ResultRow): string {
  if (!card.validation) return 'bg-stone-300';
  const statuses = Object.values(card.validation).map((v) => v.status);
  if (statuses.includes('invalid'))   return 'bg-red-500';
  if (statuses.includes('corrected')) return 'bg-amber-500';
  if (statuses.includes('verified'))  return 'bg-teal-500';
  if (statuses.includes('valid'))     return 'bg-green-500';
  return 'bg-stone-300';
}

/** Derive the filtered card list from all cards + filter type */
export function filterCards(cards: ResultRow[], filter: ValidationFilter): ResultRow[] {
  if (filter === 'all') return cards;
  return cards.filter((r) => {
    if (!r.validation) return false;
    const statuses = Object.values(r.validation).map((v) => v.status);
    if (filter === 'invalid')   return statuses.includes('invalid');
    if (filter === 'corrected') return statuses.includes('corrected');
    if (filter === 'valid')     return statuses.length > 0 && statuses.every((s) => s === 'valid');
    if (filter === 'verified')  return statuses.includes('verified');
    return false;
  });
}

export const Filmstrip: React.FC<FilmstripProps> = ({
  cards,
  activeIndex,
  filter,
  onFilterChange,
  onCardSelect,
  batchId,
}) => {
  const activeThumbRef = useRef<HTMLButtonElement>(null);
  const filteredCards = filterCards(cards, filter);

  // Auto-scroll active thumbnail into view when activeIndex changes
  useEffect(() => {
    activeThumbRef.current?.scrollIntoView({
      behavior: 'smooth',
      inline: 'center',
      block: 'nearest',
    });
  }, [activeIndex]);

  // Count per-filter for chip badges
  const counts: Record<ValidationFilter, number> = {
    all: cards.length,
    invalid: 0,
    corrected: 0,
    valid: 0,
    verified: 0,
  };
  for (const r of cards) {
    if (!r.validation) continue;
    const ss = Object.values(r.validation).map((v) => v.status);
    if (ss.includes('invalid'))   counts.invalid++;
    if (ss.includes('corrected')) counts.corrected++;
    if (ss.includes('verified'))  counts.verified++;
    if (ss.length > 0 && ss.every((s) => s === 'valid')) counts.valid++;
  }

  return (
    <div className="bg-parchment border-t border-archive-200 flex flex-col shrink-0">
      {/* Filter chip row */}
      <div className="flex flex-wrap gap-1.5 px-3 pt-2 pb-1 items-center">
        <span className="text-xs uppercase tracking-wider text-archive-ink/40 font-semibold pr-1 shrink-0">
          Filter:
        </span>
        {FILTER_CHIPS.map(({ key, label }) => {
          const isActive = filter === key;
          const count = counts[key];
          return (
            <button
              key={key}
              onClick={() => onFilterChange(key)}
              className={[
                'inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold border transition-colors',
                isActive
                  ? 'bg-archive-sepia text-parchment-light border-archive-sepia'
                  : 'bg-transparent text-archive-ink/60 border-parchment-dark hover:border-archive-sepia hover:text-archive-ink',
              ].join(' ')}
            >
              {label}
              <span
                className={[
                  'inline-flex items-center justify-center rounded-full px-1 text-xs font-mono min-w-[1.2rem]',
                  isActive
                    ? 'bg-parchment-light/30 text-parchment-light'
                    : 'bg-parchment-dark/30 text-archive-ink/50',
                ].join(' ')}
              >
                {count}
              </span>
            </button>
          );
        })}
        <span className="ml-auto text-xs text-archive-ink/40 font-mono shrink-0">
          {activeIndex + 1} / {filteredCards.length || 1}
        </span>
      </div>

      {/* Thumbnail strip */}
      <div className="overflow-x-auto flex gap-1.5 px-3 pb-2 scroll-smooth">
        {filteredCards.length === 0 ? (
          <div className="flex items-center justify-center w-full py-2 text-xs text-archive-ink/40 italic font-serif">
            No cards match this filter
          </div>
        ) : (
          filteredCards.map((card, idx) => {
            const isActive = idx === activeIndex;
            const dotClass = getStatusDotClass(card);
            const thumbUrl = `/batches-static/${batchId}/${card.filename}`;
            return (
              <button
                key={card.filename}
                ref={isActive ? activeThumbRef : null}
                onClick={() => onCardSelect(idx)}
                title={card.filename}
                className={[
                  'relative shrink-0 rounded overflow-hidden border-2 transition-all duration-150',
                  isActive
                    ? 'border-archive-600 ring-2 ring-archive-600/40'
                    : 'border-parchment-dark/40 hover:border-archive-400',
                ].join(' ')}
                style={{ width: '48px', height: '60px' }}
              >
                <img
                  src={thumbUrl}
                  alt={card.filename}
                  className="object-cover w-full h-full"
                  loading="lazy"
                />
                {/* Status dot — top-right corner */}
                <span
                  className={`absolute top-0.5 right-0.5 w-2 h-2 rounded-full ${dotClass} ring-1 ring-white`}
                />
              </button>
            );
          })
        )}
      </div>
    </div>
  );
};
