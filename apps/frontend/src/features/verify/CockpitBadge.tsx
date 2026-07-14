import React, { useState } from 'react';
import { CheckCircle, CheckCircle2, XCircle, Wand2, Link2 } from 'lucide-react';
import { useWizardStore } from '../../store/wizardStore';
import type { ValidationOutcome } from '../../api/batchesApi';

interface CockpitBadgeProps {
  outcome?: ValidationOutcome | null;
  filename: string;
  field: string;
  onMarkVerified?: () => void;
}

export const CockpitBadge: React.FC<CockpitBadgeProps> = ({
  outcome,
  filename,
  field,
  onMarkVerified,
}) => {
  const { acceptCorrectorProposal, rejectCorrectorProposal } = useWizardStore();
  const [tooltipOpen, setTooltipOpen] = useState(false);
  const [reconTooltipOpen, setReconTooltipOpen] = useState(false);

  // Reconciliation badge is shown regardless of validation status (independent dimension)
  const reconciliation = outcome?.reconciliation ?? null;

  if (!outcome || outcome.status === 'skipped') {
    // Still render reconciliation badge even if status is skipped or outcome is absent
    if (!reconciliation) return null;
    return (
      <span className="relative inline-flex items-start shrink-0">
        <span
          onMouseEnter={() => setReconTooltipOpen(true)}
          onMouseLeave={() => setReconTooltipOpen(false)}
          className="inline-flex cursor-pointer"
        >
          <Link2 size={14} className="text-blue-600 hover:text-blue-800" aria-label={`Reconciled: ${reconciliation.label}`} />
        </span>
        {reconTooltipOpen && (
          <span
            className="absolute z-50 top-5 left-0 min-w-[180px] max-w-[260px] rounded-md border border-parchment-dark/60 bg-parchment-light shadow-lg p-2.5 pointer-events-auto"
            onMouseEnter={() => setReconTooltipOpen(true)}
            onMouseLeave={() => setReconTooltipOpen(false)}
          >
            <p className="text-xs font-semibold text-archive-ink/80">{reconciliation.label}</p>
            <p className="text-xs text-archive-ink/60 mt-0.5">{reconciliation.authority}</p>
            <a
              href={reconciliation.uri}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-blue-600 hover:underline block truncate mt-0.5"
            >
              {reconciliation.uri}
            </a>
          </span>
        )}
      </span>
    );
  }

  const { status, rule_failed, original_value, corrector_proposal, rationale } = outcome;

  const iconProps = { className: 'w-4 h-4 shrink-0 cursor-pointer' };

  let icon: React.ReactNode;
  let tooltipContent: React.ReactNode;

  if (status === 'valid') {
    icon = (
      <CheckCircle
        {...iconProps}
        className={`${iconProps.className} text-emerald-600`}
      />
    );
    tooltipContent = (
      <p className="text-xs text-archive-ink/80">Rule passed.</p>
    );
  } else if (status === 'invalid') {
    icon = (
      <XCircle
        {...iconProps}
        className={`${iconProps.className} text-red-600`}
      />
    );
    tooltipContent = (
      <div className="space-y-1">
        {rule_failed && (
          <p className="text-xs text-archive-ink/80">
            <span className="font-semibold text-red-600">Rule failed:</span> {rule_failed}
          </p>
        )}
        {original_value != null && (
          <p className="text-xs text-archive-ink/60">
            <span className="font-semibold">Value:</span> {original_value}
          </p>
        )}
      </div>
    );
  } else if (status === 'corrected') {
    icon = (
      <Wand2
        {...iconProps}
        className={`${iconProps.className} text-amber-600`}
      />
    );
    tooltipContent = (
      <div className="space-y-1.5">
        {corrector_proposal != null && (
          <p className="text-xs text-archive-ink/80">
            <span className="font-semibold text-amber-700">Proposed:</span> {corrector_proposal}
          </p>
        )}
        {rationale && (
          <p className="text-xs text-archive-ink/60 italic">{rationale}</p>
        )}
        <div className="flex gap-1.5 pt-0.5">
          <button
            onClick={(e) => {
              e.stopPropagation();
              acceptCorrectorProposal(filename, field);
              setTooltipOpen(false);
            }}
            className="px-2 py-0.5 text-xs rounded bg-emerald-600 text-white hover:bg-emerald-700 transition-colors font-semibold"
          >
            Accept
          </button>
          <button
            onClick={(e) => {
              e.stopPropagation();
              rejectCorrectorProposal(filename, field);
              setTooltipOpen(false);
            }}
            className="px-2 py-0.5 text-xs rounded bg-red-600 text-white hover:bg-red-700 transition-colors font-semibold"
          >
            Reject
          </button>
        </div>
      </div>
    );
  } else if (status === 'verified') {
    // CheckCircle2 = distinct filled double-ring icon; text-emerald-700 is darker than valid's emerald-600
    icon = (
      <CheckCircle2
        {...iconProps}
        className={`${iconProps.className} text-emerald-700`}
        onClick={onMarkVerified}
      />
    );
    tooltipContent = (
      <p className="text-xs text-archive-ink/80">Curator verified.</p>
    );
  } else {
    return null;
  }

  return (
    <span className="inline-flex items-start gap-0.5 shrink-0">
      {/* Validation status icon with tooltip */}
      <span className="relative inline-flex items-start shrink-0">
        <span
          onClick={() => setTooltipOpen((v) => !v)}
          onMouseEnter={() => setTooltipOpen(true)}
          onMouseLeave={() => status !== 'corrected' && setTooltipOpen(false)}
          className="inline-flex cursor-pointer"
        >
          {icon}
        </span>

        {tooltipOpen && (
          <span
            className="absolute z-50 top-5 left-0 min-w-[180px] max-w-[260px] rounded-md border border-parchment-dark/60 bg-parchment-light shadow-lg p-2.5 pointer-events-auto"
            onMouseEnter={() => setTooltipOpen(true)}
            onMouseLeave={() => setTooltipOpen(false)}
          >
            {tooltipContent}
          </span>
        )}
      </span>

      {/* Reconciliation badge — shown independently of validation status when reconciliation is set */}
      {reconciliation && (
        <span className="relative inline-flex items-start shrink-0">
          <span
            onMouseEnter={() => setReconTooltipOpen(true)}
            onMouseLeave={() => setReconTooltipOpen(false)}
            className="inline-flex cursor-pointer"
          >
            <Link2 size={14} className="text-blue-600 hover:text-blue-800" aria-label={`Reconciled: ${reconciliation.label}`} />
          </span>
          {reconTooltipOpen && (
            <span
              className="absolute z-50 top-5 left-0 min-w-[180px] max-w-[260px] rounded-md border border-parchment-dark/60 bg-parchment-light shadow-lg p-2.5 pointer-events-auto"
              onMouseEnter={() => setReconTooltipOpen(true)}
              onMouseLeave={() => setReconTooltipOpen(false)}
            >
              <p className="text-xs font-semibold text-archive-ink/80">{reconciliation.label}</p>
              <p className="text-xs text-archive-ink/60 mt-0.5">{reconciliation.authority}</p>
              <a
                href={reconciliation.uri}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-blue-600 hover:underline block truncate mt-0.5"
              >
                {reconciliation.uri}
              </a>
            </span>
          )}
        </span>
      )}
    </span>
  );
};
