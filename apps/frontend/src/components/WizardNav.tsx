import React from 'react';
import { ArrowLeft, Loader2 } from 'lucide-react';

interface WizardNavProps {
  back?: {
    label: string;
    onClick: () => void;
    disabled?: boolean;
    icon?: React.ReactNode;
  };
  next?: {
    label: string;
    onClick: () => void;
    disabled?: boolean;
    loading?: boolean;
    icon?: React.ReactNode;
  };
}

export const WizardNav: React.FC<WizardNavProps> = ({ back, next }) => {
  return (
    <div className="sticky bottom-0 z-10 mt-auto">
      <div className="bg-parchment border border-parchment-dark/50 rounded-lg parchment-shadow flex justify-between items-center px-6 py-3">
        {/* Back button (left side) */}
        {back ? (
          <button
            onClick={back.onClick}
            disabled={back.disabled}
            className="flex items-center gap-2 font-serif text-lg px-6 py-2.5 rounded transition-all text-archive-ink/60 hover:text-archive-sepia hover:bg-parchment-dark/10 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {back.icon ?? <ArrowLeft className="w-5 h-5" />}
            {back.label}
          </button>
        ) : (
          <div />
        )}

        {/* Next button (right side) */}
        {next ? (
          <button
            onClick={next.onClick}
            disabled={next.disabled || next.loading}
            className={`
              flex items-center gap-2 font-serif text-lg px-6 py-2.5 rounded transition-all
              ${
                !next.disabled && !next.loading
                  ? 'bg-archive-sepia text-parchment-light shadow-lg hover:bg-archive-sepia/90 active:scale-95'
                  : 'bg-parchment-dark/30 text-archive-ink/20 cursor-not-allowed'
              }
            `}
          >
            {next.loading ? (
              <>
                <Loader2 className="w-5 h-5 animate-spin" />
                {next.label}
              </>
            ) : (
              <>
                {next.label}
                {next.icon}
              </>
            )}
          </button>
        ) : (
          <div />
        )}
      </div>
    </div>
  );
};
