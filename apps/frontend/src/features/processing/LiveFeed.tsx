import React, { useEffect, useRef } from 'react';
import type { ExtractionResult } from '../../store/wizardStore';

interface LiveFeedProps {
  items: ExtractionResult[];
}

export const LiveFeed: React.FC<LiveFeedProps> = ({ items }) => {
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (items.length > 0) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [items.length]);

  if (items.length === 0) {
    return (
      <div className="max-h-64 overflow-y-auto border border-parchment-dark/30 rounded-lg bg-parchment-light/10 p-4">
        <p className="text-archive-ink/40 italic text-sm text-center">
          Awaiting first result...
        </p>
      </div>
    );
  }

  return (
    <div className="max-h-64 overflow-y-auto border border-parchment-dark/30 rounded-lg space-y-2 p-2">
      {items.map((item, index) => (
        <div
          key={`${item.filename}-${index}`}
          className={
            item.success
              ? 'border-l-4 border-green-700/30 bg-parchment-light/30 p-3 rounded-r'
              : 'border-l-4 border-red-500/30 bg-red-50/20 p-3 rounded-r'
          }
        >
          <p className="font-mono text-xs font-semibold text-archive-ink/70 truncate mb-1">
            {item.filename}
          </p>
          {item.success && item.data ? (
            <div className="grid grid-cols-2 gap-x-4 gap-y-0.5">
              {Object.entries(item.data).map(([key, value]) => (
                <div key={key} className="flex gap-1 text-xs text-archive-ink/60 truncate">
                  <span className="font-semibold shrink-0">{key}:</span>
                  <span className="truncate font-serif italic">{value || '—'}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-red-700/70 italic">{item.error ?? 'Unknown error'}</p>
          )}
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  );
};
