import React from 'react';

export type ValidationFilter = 'all' | 'invalid' | 'corrected' | 'valid';

interface ValidationFilterChipsProps {
  value: ValidationFilter;
  onChange: (v: ValidationFilter) => void;
  counts: { all: number; invalid: number; corrected: number; valid: number };
}

const CHIPS: Array<{ key: ValidationFilter; label: string }> = [
  { key: 'all',       label: 'All' },
  { key: 'invalid',   label: 'Invalid' },
  { key: 'corrected', label: 'Auto-corrected' },
  { key: 'valid',     label: 'Verified OK' },
];

export const ValidationFilterChips: React.FC<ValidationFilterChipsProps> = ({
  value,
  onChange,
  counts,
}) => {
  return (
    <div className="flex flex-wrap gap-2 items-center">
      <span className="text-xs uppercase tracking-wider text-archive-ink/40 font-semibold pr-1">
        Filter:
      </span>
      {CHIPS.map(({ key, label }) => {
        const isActive = value === key;
        const count = counts[key];
        return (
          <button
            key={key}
            onClick={() => onChange(key)}
            className={[
              'inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold border transition-colors',
              isActive
                ? 'bg-archive-sepia text-parchment-light border-archive-sepia'
                : 'bg-transparent text-archive-ink/60 border-parchment-dark hover:border-archive-sepia hover:text-archive-ink',
            ].join(' ')}
          >
            {label}
            <span
              className={[
                'inline-flex items-center justify-center rounded-full px-1.5 py-px text-xs font-mono min-w-[1.2rem]',
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
    </div>
  );
};
