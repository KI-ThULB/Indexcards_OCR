import React, { useState } from 'react';
import { FileSpreadsheet, FileJson, FileCode, RotateCcw, ChevronDown } from 'lucide-react';
import type { ResultRow } from '../../store/wizardStore';

interface SummaryBannerProps {
  results: ResultRow[];
  batchName: string;
  totalDuration: number;
  onDownloadCSV: () => void;
  onDownloadJSON: () => void;
  onDownloadLIDO: () => void;
  onDownloadEAD: () => void;
  onDownloadDarwinCore: () => void;
  onDownloadDublinCore: () => void;
  onDownloadMARCXML: () => void;
  onDownloadMETSMODS: () => void;
  onRetryAllFailed: () => void;
  failedCount: number;
  invalidCount?: number;
  correctedCount?: number;
  isProcessing: boolean;
}

const statLabel = 'text-xs uppercase tracking-widest text-archive-ink/40 font-semibold';
const statValue = 'font-mono text-archive-sepia font-bold text-lg';
const btnBase =
  'flex items-center gap-2 px-3 py-2 border border-archive-sepia/40 bg-archive-sepia/10 rounded text-xs uppercase tracking-widest text-archive-sepia hover:bg-archive-sepia/20 transition-colors whitespace-nowrap';

export const SummaryBanner: React.FC<SummaryBannerProps> = ({
  results,
  batchName,
  totalDuration,
  onDownloadCSV,
  onDownloadJSON,
  onDownloadLIDO,
  onDownloadEAD,
  onDownloadDarwinCore,
  onDownloadDublinCore,
  onDownloadMARCXML,
  onDownloadMETSMODS,
  onRetryAllFailed,
  failedCount,
  invalidCount,
  correctedCount,
  isProcessing,
}) => {
  const successCount = results.filter((r) => r.status === 'success').length;
  const [xmlOpen, setXmlOpen] = useState(false);

  return (
    <div className="parchment-shadow border border-parchment-dark/50 rounded-lg p-4 flex flex-wrap items-start justify-between gap-4 bg-parchment-light/30">
      {/* Stats */}
      <div className="flex flex-wrap gap-6">
        <div className="flex flex-col">
          <span className={statLabel}>Batch</span>
          <span className="font-mono text-archive-ink font-semibold text-sm truncate max-w-48">{batchName}</span>
        </div>
        <div className="flex flex-col">
          <span className={statLabel}>Total</span>
          <span className={statValue}>{results.length}</span>
        </div>
        <div className="flex flex-col">
          <span className={statLabel}>Success</span>
          <span className={`${statValue} text-green-700`}>{successCount}</span>
        </div>
        <div className="flex flex-col">
          <span className={statLabel}>Errors</span>
          <span className={`${statValue} ${failedCount > 0 ? 'text-red-600' : 'text-archive-sepia'}`}>
            {failedCount}
          </span>
        </div>
        <div className="flex flex-col">
          <span className={statLabel}>Duration</span>
          <span className={statValue}>{totalDuration.toFixed(1)}s</span>
        </div>
        {invalidCount !== undefined && invalidCount > 0 && (
          <div className="flex flex-col">
            <span className={statLabel}>Invalid</span>
            <span className={`${statValue} text-amber-700`}>{invalidCount}</span>
          </div>
        )}
        {correctedCount !== undefined && correctedCount > 0 && (
          <div className="flex flex-col">
            <span className={statLabel}>Proposals</span>
            <span className={`${statValue} text-blue-700`}>{correctedCount}</span>
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="flex flex-wrap gap-2 items-start">
        {failedCount > 0 && (
          <button
            onClick={onRetryAllFailed}
            disabled={isProcessing}
            className="flex items-center gap-2 px-3 py-2 border border-parchment-dark rounded text-xs uppercase tracking-widest text-archive-ink/60 hover:text-archive-ink hover:border-archive-sepia transition-colors disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            Retry All Failed
          </button>
        )}

        <button onClick={onDownloadCSV} className={btnBase}>
          <FileSpreadsheet className="w-3.5 h-3.5" />
          CSV
        </button>
        <button onClick={onDownloadJSON} className={btnBase}>
          <FileJson className="w-3.5 h-3.5" />
          JSON
        </button>

        {/* XML formats dropdown */}
        <div className="relative">
          <button onClick={() => setXmlOpen((v) => !v)} className={btnBase}>
            <FileCode className="w-3.5 h-3.5" />
            XML
            <ChevronDown className={`w-3 h-3 transition-transform ${xmlOpen ? 'rotate-180' : ''}`} />
          </button>
          {xmlOpen && (
            <div className="absolute right-0 top-full mt-1 z-50 flex flex-col min-w-[160px] rounded-lg border border-parchment-dark/60 bg-parchment-light shadow-lg overflow-hidden">
              {([
                { label: 'MARC21-XML (K10plus)', action: onDownloadMARCXML },
                { label: 'METS/MODS',            action: onDownloadMETSMODS },
                { label: 'LIDO-XML 1.1',         action: onDownloadLIDO },
                { label: 'EAD',                  action: onDownloadEAD },
                { label: 'Darwin Core',          action: onDownloadDarwinCore },
                { label: 'Dublin Core',          action: onDownloadDublinCore },
              ] as const).map(({ label, action }) => (
                <button
                  key={label}
                  onClick={() => { action(); setXmlOpen(false); }}
                  className="flex items-center gap-2 px-4 py-2.5 text-xs font-mono text-archive-ink/70 hover:bg-archive-sepia/10 hover:text-archive-sepia transition-colors text-left whitespace-nowrap"
                >
                  <FileCode className="w-3 h-3 shrink-0" />
                  {label}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
