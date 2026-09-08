import React, { useCallback, useEffect, useState, useSyncExternalStore } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  CircleSlash,
  Loader2,
  Pause,
  Play,
  XCircle,
} from 'lucide-react';
import { toast } from 'sonner';
import {
  useBulkRunQuery,
  useCancelBulkRunMutation,
  usePauseBulkRunMutation,
  useResumeBulkRunMutation,
  isTerminal,
} from '../../api/bulkApi';
import type { BulkFolderProgress, BulkProgress } from '../../api/bulkApi';
import { useBulkStore } from '../../store/bulkStore';
import { BulkWarning } from './BulkWarning';
import { useBulkWebSocket } from './useBulkWebSocket';

/**
 * A ticking wall clock as an external store.
 *
 * The elapsed counter needs the current time during render, and Date.now() is
 * impure — so it is read through useSyncExternalStore, whose getSnapshot
 * contract is exactly "read the current value of an external mutable source".
 * That also avoids seeding state from an effect. Resolution is one second,
 * which is all the display shows.
 */
const subscribeToClock = (onChange: () => void) => {
  const timer = setInterval(onChange, 1000);
  return () => clearInterval(timer);
};
const noCleanup = () => {};
const clockSnapshot = () => Math.floor(Date.now() / 1000) * 1000;

/**
 * The run's persisted status. `pause_requested` / `cancel_requested` are
 * deliberately NOT statuses of their own: they are transient runtime state that
 * the backend already puts on the wire, so no schema had to grow for the UI to
 * distinguish "running" from "stopping".
 */
const STATUS_LABELS: Record<BulkProgress['status'], string> = {
  queued: 'In Warteschlange',
  running: 'Läuft',
  paused: 'Pausiert',
  interrupted: 'Unterbrochen',
  completed: 'Abgeschlossen',
  completed_with_errors: 'Mit Fehlern abgeschlossen',
  failed: 'Fehlgeschlagen',
  cancelled: 'Abgebrochen',
};

const PAUSE_REQUESTED_LABEL = 'Pause wird vorbereitet…';
const CANCEL_REQUESTED_LABEL = 'Abbruch wird durchgeführt…';

function formatElapsed(
  startedAt: string | null | undefined,
  endedAt: string | null | undefined,
  now: number
) {
  if (!startedAt) return '—';
  const start = new Date(startedAt).getTime();
  const end = endedAt ? new Date(endedAt).getTime() : now;
  const seconds = Math.max(0, Math.floor((end - start) / 1000));
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return h > 0 ? `${h}h ${m}m ${s}s` : m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function formatTimestamp(iso?: string | null) {
  if (!iso) return '—';
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
}

const FOLDER_ICONS: Record<BulkFolderProgress['status'], React.ReactNode> = {
  pending: <CircleSlash className="w-4 h-4 text-archive-ink/25" />,
  running: <Loader2 className="w-4 h-4 text-archive-sepia animate-spin" />,
  completed: <CheckCircle2 className="w-4 h-4 text-green-700" />,
  completed_with_errors: <AlertTriangle className="w-4 h-4 text-amber-700" />,
  failed: <XCircle className="w-4 h-4 text-red-700" />,
  skipped: <CircleSlash className="w-4 h-4 text-archive-ink/25" />,
};

const Stat: React.FC<{ label: string; value: React.ReactNode }> = ({ label, value }) => (
  <div className="space-y-1">
    <dt className="text-[10px] uppercase tracking-widest text-archive-ink/40 font-semibold">
      {label}
    </dt>
    <dd className="font-serif text-lg text-archive-ink tabular-nums">{value}</dd>
  </div>
);

/**
 * Live progress for a running, paused or interrupted bulk run.
 *
 * State comes from the backend, pushed over the WebSocket and backed by a
 * polled query, so closing the browser or reloading mid-run re-attaches to the
 * same job instead of losing it.
 */
export const BulkProgressStep: React.FC = () => {
  const { runId, setStep, resetBulk } = useBulkStore();
  const query = useBulkRunQuery(runId);
  const [live, setLive] = useState<BulkProgress | null>(null);

  const pause = usePauseBulkRunMutation();
  const resume = useResumeBulkRunMutation();
  const cancel = useCancelBulkRunMutation();

  useBulkWebSocket(runId, setLive);

  // Prefer the pushed state when it is for this run; fall back to the query.
  const run = live && live.bulk_run_id === runId ? live : query.data ?? null;

  // Only tick while the run is actually in flight; a finished run's elapsed
  // time is fixed, so there is nothing to animate.
  const ticking = !!run && !isTerminal(run.status);
  const subscribe = useCallback(
    (onChange: () => void) => (ticking ? subscribeToClock(onChange) : noCleanup),
    [ticking]
  );
  const now = useSyncExternalStore(subscribe, clockSnapshot);

  useEffect(() => {
    if (run && isTerminal(run.status)) setStep('summary');
  }, [run?.status, run, setStep]);

  if (!runId) {
    return (
      <div className="space-y-4">
        <p className="text-sm text-archive-ink/60">No bulk run selected.</p>
        <button onClick={resetBulk} className="text-sm text-archive-sepia hover:underline">
          Back to bulk processing
        </button>
      </div>
    );
  }

  if (!run) {
    return (
      <div className="flex items-center gap-2 text-archive-ink/40 text-sm italic py-6">
        <Loader2 className="w-4 h-4 animate-spin" />
        Loading run&hellip;
      </div>
    );
  }

  const percentage =
    run.images_total > 0 ? Math.min(100, (run.images_processed / run.images_total) * 100) : 0;
  const currentFolder = run.folders.find((f) => f.source_folder === run.current_folder) ?? null;
  const isRunning = run.status === 'running';
  const canResume = run.status === 'paused' || run.status === 'interrupted';

  // A stop is pending while the run still runs. Cancel outranks pause: once a
  // cancel is registered the run will not come back as paused.
  //
  // Three sources, because one is not enough. `run` prefers the pushed
  // WebSocket state, which is only as fresh as the backend's last broadcast —
  // and it was precisely a missing broadcast that made Pause look like a
  // no-op. The mutation's own response is the backend's confirmation of *this*
  // request, and `isPending` covers the round trip. Resume clears the
  // mutations, so a stop from a previous leg cannot leak into the next one.
  const pauseConfirmed = pause.data?.bulk_run_id === run.bulk_run_id && pause.data.pause_requested;
  const cancelConfirmed =
    cancel.data?.bulk_run_id === run.bulk_run_id && cancel.data.cancel_requested;
  const cancelPending = isRunning && (run.cancel_requested || cancel.isPending || !!cancelConfirmed);
  const pausePending =
    isRunning && !cancelPending && (run.pause_requested || pause.isPending || !!pauseConfirmed);
  const stopPending = pausePending || cancelPending;
  // The folder in flight still has a card at the model — the one the backend
  // finishes before it stops.
  const cardStillRunning = stopPending && currentFolder?.status === 'running';

  const statusLabel = cancelPending
    ? CANCEL_REQUESTED_LABEL
    : pausePending
      ? PAUSE_REQUESTED_LABEL
      : STATUS_LABELS[run.status];

  return (
    <div className="space-y-6">
      <header className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <h2 className="font-serif text-2xl text-archive-ink">{run.name}</h2>
          <p className="text-sm text-archive-ink/50 font-mono">
            {run.provider}
            {run.model ? ` · ${run.model}` : ''}
          </p>
        </div>
        <span
          className={`px-3 py-1 rounded text-xs uppercase tracking-widest font-semibold ${
            run.status === 'failed'
              ? 'bg-red-700/10 text-red-800'
              : run.status === 'interrupted' || run.status === 'paused' || stopPending
                ? 'bg-amber-700/10 text-amber-800'
                : 'bg-archive-sepia/10 text-archive-sepia'
          }`}
        >
          {statusLabel}
        </span>
      </header>

      {/* ── Pause / Abbruch angefordert ────────────────────────────────── */}
      {stopPending && (
        <div className="flex gap-3 p-4 rounded border border-amber-700/50 bg-amber-700/5">
          {cancelPending ? (
            <XCircle className="w-5 h-5 text-amber-700 shrink-0 mt-0.5" />
          ) : (
            <Pause className="w-5 h-5 text-amber-700 shrink-0 mt-0.5" />
          )}
          <div className="space-y-1 text-sm text-archive-ink/80">
            <p className="font-semibold">
              {cancelPending ? 'Abbruch angefordert' : 'Pause angefordert'}
            </p>
            <p className="leading-relaxed">
              {cardStillRunning
                ? cancelPending
                  ? 'Aktuelle Karte wird noch abgeschlossen; danach wird der Lauf beendet. Es wird keine weitere Karte gestartet.'
                  : 'Aktuelle Karte wird noch abgeschlossen … Danach wird keine weitere Karte gestartet.'
                : cancelPending
                  ? 'Es wird keine weitere Karte gestartet; der Lauf wird beendet.'
                  : 'Es wird keine weitere Karte gestartet; der Lauf wird pausiert.'}
            </p>
            <p className="leading-relaxed text-archive-ink/60">
              Bereits abgeschlossene Karten bleiben erhalten und sind exportierbar.
            </p>
          </div>
        </div>
      )}

      {/* ── Interrupted banner ─────────────────────────────────────────── */}
      {run.status === 'interrupted' && (
        <div className="flex gap-3 p-4 rounded border border-amber-700/50 bg-amber-700/5">
          <AlertTriangle className="w-5 h-5 text-amber-700 shrink-0 mt-0.5" />
          <div className="space-y-2 text-sm text-archive-ink/80">
            <p className="font-semibold">
              This run was interrupted when the backend stopped.
            </p>
            <p className="leading-relaxed">
              Nothing is resumed automatically, so no images are sent to the
              model until you choose to continue. Folders already completed are
              skipped, and images already extracted are not processed again.
            </p>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 font-mono text-xs pt-1">
              <dt className="text-archive-ink/50">Last folder</dt>
              <dd>{run.current_folder ?? '—'}</dd>
              <dt className="text-archive-ink/50">Last image</dt>
              <dd>{run.last_image ?? '—'}</dd>
              <dt className="text-archive-ink/50">Interrupted at</dt>
              <dd>{formatTimestamp(run.interrupted_at)}</dd>
            </dl>
          </div>
        </div>
      )}

      {run.status === 'failed' && run.error && (
        <div className="flex gap-3 p-4 rounded border border-red-700/40 bg-red-700/5">
          <XCircle className="w-5 h-5 text-red-700 shrink-0 mt-0.5" />
          <p className="text-sm text-archive-ink/80">{run.error}</p>
        </div>
      )}

      <BulkWarning />

      {/* ── Overall progress ───────────────────────────────────────────── */}
      <section className="space-y-3">
        <div className="flex justify-between text-xs uppercase tracking-widest text-archive-ink/40 font-semibold">
          <span>
            {run.images_processed.toLocaleString()} / {run.images_total.toLocaleString()} images
          </span>
          <span>{percentage.toFixed(1)}%</span>
        </div>
        <div className="h-2 bg-parchment-dark rounded overflow-hidden">
          <div
            className="h-full bg-archive-sepia transition-all duration-500 ease-out"
            style={{ width: `${percentage}%` }}
          />
        </div>
      </section>

      <dl className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4 p-4 rounded border border-parchment-dark/60 bg-parchment-light/20">
        <Stat label="Folders" value={`${run.folders_completed} / ${run.folders_total}`} />
        <Stat label="Current folder" value={run.current_folder ?? '—'} />
        <Stat
          label="In this folder"
          value={
            currentFolder
              ? `${currentFolder.images_processed} / ${currentFolder.images_total}`
              : '—'
          }
        />
        <Stat label="Images overall" value={run.images_processed.toLocaleString()} />
        <Stat
          label="Failed images"
          value={
            <span className={run.images_failed > 0 ? 'text-amber-700' : undefined}>
              {run.images_failed.toLocaleString()}
            </span>
          }
        />
        <Stat label="Elapsed" value={formatElapsed(run.started_at, run.completed_at, now)} />
      </dl>

      {run.last_image && isRunning && (
        <p className="font-mono text-sm text-archive-ink/50 truncate">
          {stopPending ? 'Zuletzt verarbeitet' : 'In Verarbeitung'}: {run.last_image}
        </p>
      )}

      {/* ── Controls ───────────────────────────────────────────────────── */}
      <div className="flex flex-wrap gap-3">
        {isRunning && (
          <button
            onClick={() => {
              pause.mutate(run.bulk_run_id);
              toast.info('Pause angefordert — der Lauf stoppt nach der aktuellen Karte.');
            }}
            // Also disabled once a cancel is pending: a cancel supersedes a
            // pause, and letting both be clicked is what produced the
            // pause/cancel/pause bursts in the audit log.
            disabled={stopPending}
            className="flex items-center gap-2 px-4 py-2 rounded border border-parchment-dark/60 text-sm text-archive-ink hover:bg-parchment-dark/20 disabled:opacity-40 transition-colors"
          >
            <Pause className="w-4 h-4" />
            {pausePending ? PAUSE_REQUESTED_LABEL : 'Pause'}
          </button>
        )}
        {canResume && (
          <button
            onClick={() =>
              resume.mutate(run.bulk_run_id, {
                // Forget the stop that produced this pause, so the resumed run
                // is not immediately displayed as stopping again.
                onSuccess: () => {
                  pause.reset();
                  cancel.reset();
                },
              })
            }
            disabled={resume.isPending}
            className="flex items-center gap-2 px-4 py-2 rounded bg-archive-sepia text-parchment text-sm font-medium hover:bg-archive-sepia/90 disabled:opacity-40 transition-colors"
          >
            {resume.isPending ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Play className="w-4 h-4" />
            )}
            Fortsetzen
          </button>
        )}
        {isRunning && (
          <button
            onClick={() => {
              cancel.mutate(run.bulk_run_id);
              toast.info(
                'Abbruch angefordert — abgeschlossene Ergebnisse bleiben erhalten.'
              );
            }}
            // A pause may still be escalated to a cancel, so only a pending
            // cancel disables this.
            disabled={cancelPending}
            className="flex items-center gap-2 px-4 py-2 rounded border border-red-700/40 text-sm text-red-800 hover:bg-red-700/5 disabled:opacity-40 transition-colors"
          >
            <XCircle className="w-4 h-4" />
            {cancelPending ? CANCEL_REQUESTED_LABEL : 'Abbrechen'}
          </button>
        )}
        {isTerminal(run.status) && (
          <button
            onClick={() => setStep('summary')}
            className="px-4 py-2 rounded bg-archive-sepia text-parchment text-sm font-medium hover:bg-archive-sepia/90 transition-colors"
          >
            View summary
          </button>
        )}
      </div>

      {/* ── Per-folder detail ──────────────────────────────────────────── */}
      <section className="space-y-2">
        <h3 className="text-xs uppercase tracking-widest text-archive-sepia/60 font-semibold">
          Folders
        </h3>
        <div className="rounded border border-parchment-dark/60 divide-y divide-parchment-dark/40 max-h-80 overflow-y-auto">
          {run.folders.map((folder) => (
            <div
              key={folder.source_folder}
              className="flex items-center gap-3 px-3 py-2 text-sm"
            >
              {FOLDER_ICONS[folder.status]}
              <span className="font-mono text-archive-ink flex-1 truncate">
                {folder.source_folder}
              </span>
              {folder.error && (
                <span className="text-xs text-red-800 truncate max-w-xs" title={folder.error}>
                  {folder.error}
                </span>
              )}
              {folder.images_failed > 0 && (
                <span className="text-xs text-amber-700 tabular-nums">
                  {folder.images_failed} failed
                </span>
              )}
              <span className="text-xs text-archive-ink/50 tabular-nums">
                {folder.images_processed} / {folder.images_total}
              </span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
};
