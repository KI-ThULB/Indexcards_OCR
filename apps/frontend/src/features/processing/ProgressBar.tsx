import React from 'react';
import type { BatchProgress } from '../../store/wizardStore';

interface ProgressBarProps {
  progress: BatchProgress | null;
}

export const ProgressBar: React.FC<ProgressBarProps> = ({ progress }) => {
  if (!progress) {
    return (
      <div className="space-y-3">
        <div className="flex justify-between">
          <span className="text-xs uppercase tracking-widest text-archive-ink/40 font-semibold animate-pulse">
            Waiting for connection...
          </span>
        </div>
        <div className="h-2 bg-parchment-dark rounded overflow-hidden">
          <div className="h-full bg-archive-sepia/30 animate-pulse w-full" />
        </div>
      </div>
    );
  }

  const { current, total, percentage, eta_seconds, last_result } = progress;
  const etaLabel =
    eta_seconds != null && eta_seconds > 0
      ? `~${Math.ceil(eta_seconds)}s remaining`
      : null;

  return (
    <div className="space-y-3">
      <div className="flex justify-between items-center">
        <span className="text-xs uppercase tracking-widest text-archive-ink/40 font-semibold">
          {current} / {total} items
        </span>
        {etaLabel && (
          <span className="text-xs uppercase tracking-widest text-archive-ink/40 font-semibold">
            {etaLabel}
          </span>
        )}
      </div>

      <div className="h-2 bg-parchment-dark rounded overflow-hidden">
        <div
          className="h-full bg-archive-sepia transition-all duration-500 ease-out"
          style={{ width: `${percentage}%` }}
        />
      </div>

      {last_result?.filename && (
        <p className="font-mono text-sm text-archive-ink/50 truncate">
          Processing: {last_result.filename}
        </p>
      )}
    </div>
  );
};
