import React from 'react';
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Download,
  Loader2,
  XCircle,
} from 'lucide-react';
import {
  downloadConsolidatedCsv,
  downloadFailuresCsv,
  useBulkRunQuery,
} from '../../api/bulkApi';
import type { BulkProgress } from '../../api/bulkApi';
import { useBulkStore } from '../../store/bulkStore';

function formatDuration(startedAt?: string | null, endedAt?: string | null) {
  if (!startedAt || !endedAt) return '—';
  const seconds = Math.max(
    0,
    Math.floor((new Date(endedAt).getTime() - new Date(startedAt).getTime()) / 1000)
  );
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m ${seconds % 60}s`;
}

const HEADLINE: Record<
  BulkProgress['status'],
  { icon: React.ReactNode; text: string; tone: string }
> = {
  completed: {
    icon: <CheckCircle2 className="w-6 h-6 text-green-700" />,
    text: 'Run completed',
    tone: 'border-green-700/40 bg-green-700/5',
  },
  completed_with_errors: {
    icon: <AlertTriangle className="w-6 h-6 text-amber-700" />,
    text: 'Run completed with errors',
    tone: 'border-amber-700/40 bg-amber-700/5',
  },
  failed: {
    icon: <XCircle className="w-6 h-6 text-red-700" />,
    text: 'Run failed',
    tone: 'border-red-700/40 bg-red-700/5',
  },
  cancelled: {
    icon: <XCircle className="w-6 h-6 text-archive-ink/50" />,
    text: 'Run cancelled',
    tone: 'border-parchment-dark/60 bg-parchment-light/20',
  },
  paused: {
    icon: <AlertTriangle className="w-6 h-6 text-amber-700" />,
    text: 'Run paused',
    tone: 'border-amber-700/40 bg-amber-700/5',
  },
  interrupted: {
    icon: <AlertTriangle className="w-6 h-6 text-amber-700" />,
    text: 'Run interrupted',
    tone: 'border-amber-700/40 bg-amber-700/5',
  },
  queued: {
    icon: <Loader2 className="w-6 h-6 text-archive-ink/40" />,
    text: 'Run queued',
    tone: 'border-parchment-dark/60 bg-parchment-light/20',
  },
  running: {
    icon: <Loader2 className="w-6 h-6 text-archive-sepia animate-spin" />,
    text: 'Run in progress',
    tone: 'border-parchment-dark/60 bg-parchment-light/20',
  },
};

/**
 * Final summary and downloads.
 *
 * Provider cost is deliberately absent: the application does not track it, and
 * an invented figure would be worse than none.
 */
export const BulkSummary: React.FC = () => {
  const { runId, setStep, resetBulk } = useBulkStore();
  const { data: run } = useBulkRunQuery(runId);

  if (!run) {
    return (
      <div className="flex items-center gap-2 text-archive-ink/40 text-sm italic py-6">
        <Loader2 className="w-4 h-4 animate-spin" />
        Loading summary&hellip;
      </div>
    );
  }

  const headline = HEADLINE[run.status];
  const succeeded = Math.max(0, run.images_processed - run.images_failed);
  const failedFolders = run.folders.filter(
    (f) => f.status === 'failed' || f.status === 'completed_with_errors'
  );

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h2 className="font-serif text-2xl text-archive-ink">{run.name}</h2>
        <p className="text-sm text-archive-ink/50 font-mono">
          {run.provider}
          {run.model ? ` · ${run.model}` : ''}
        </p>
      </header>

      <div className={`flex items-center gap-3 p-4 rounded border ${headline.tone}`}>
        {headline.icon}
        <div>
          <p className="font-serif text-lg text-archive-ink">{headline.text}</p>
          {run.error && <p className="text-sm text-archive-ink/70">{run.error}</p>}
        </div>
      </div>

      <dl className="grid grid-cols-2 sm:grid-cols-3 gap-4 p-4 rounded border border-parchment-dark/60 bg-parchment-light/20">
        {[
          ['Folders processed', `${run.folders_completed} / ${run.folders_total}`],
          ['Images total', run.images_total.toLocaleString()],
          ['Extracted successfully', succeeded.toLocaleString()],
          ['Failed images', run.images_failed.toLocaleString()],
          ['Elapsed', formatDuration(run.started_at, run.completed_at)],
          ['Fields per record', String(run.schema_fields.length)],
        ].map(([label, value]) => (
          <div key={label} className="space-y-1">
            <dt className="text-[10px] uppercase tracking-widest text-archive-ink/40 font-semibold">
              {label}
            </dt>
            <dd className="font-serif text-lg text-archive-ink tabular-nums">{value}</dd>
          </div>
        ))}
      </dl>

      <div className="flex flex-wrap gap-3">
        <button
          onClick={() => downloadConsolidatedCsv(run)}
          className="flex items-center gap-2 px-6 py-3 rounded bg-archive-sepia text-parchment font-medium hover:bg-archive-sepia/90 transition-colors"
        >
          <Download className="w-4 h-4" />
          Download consolidated CSV
        </button>
        {run.images_failed > 0 && (
          <button
            onClick={() => downloadFailuresCsv(run)}
            className="flex items-center gap-2 px-6 py-3 rounded border border-amber-700/40 text-amber-800 font-medium hover:bg-amber-700/5 transition-colors"
          >
            <Download className="w-4 h-4" />
            Download failed records
          </button>
        )}
      </div>

      <p className="text-xs text-archive-ink/50 leading-relaxed max-w-3xl">
        The consolidated CSV keeps each record&rsquo;s source folder and source
        filename, so every row remains traceable to its scan. Each folder is also
        still an ordinary batch: open it from the Batch Archive to inspect,
        verify or clean individual records before ingest.
      </p>

      {failedFolders.length > 0 && (
        <section className="space-y-2">
          <h3 className="text-xs uppercase tracking-widest text-archive-sepia/60 font-semibold">
            Folders needing attention
          </h3>
          <div className="rounded border border-parchment-dark/60 divide-y divide-parchment-dark/40">
            {failedFolders.map((folder) => (
              <div
                key={folder.source_folder}
                className="flex items-center gap-3 px-3 py-2 text-sm"
              >
                <span className="font-mono text-archive-ink flex-1 truncate">
                  {folder.source_folder}
                </span>
                <span className="text-xs text-archive-ink/60">
                  {folder.error ?? `${folder.images_failed} failed image(s)`}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      <div className="flex gap-4 pt-2">
        <button
          onClick={() => setStep('progress')}
          className="flex items-center gap-2 text-sm text-archive-ink/60 hover:text-archive-ink"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to progress
        </button>
        <button onClick={resetBulk} className="text-sm text-archive-sepia hover:underline">
          Start another bulk run
        </button>
      </div>
    </div>
  );
};
