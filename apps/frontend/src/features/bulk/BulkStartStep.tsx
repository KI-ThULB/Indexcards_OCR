import React, { useMemo } from 'react';
import {
  CheckSquare,
  FolderTree,
  LayoutGrid,
  Loader2,
  Play,
  RefreshCw,
  Square,
} from 'lucide-react';
import { toast } from 'sonner';
import {
  useBulkRunsQuery,
  useBulkSourcesQuery,
  useCreateBulkRunMutation,
  useStartBulkRunMutation,
  isResumable,
} from '../../api/bulkApi';
import { useTemplatesQuery } from '../../api/templatesApi';
import { useBulkStore } from '../../store/bulkStore';
import { ProviderSelector } from '../configure/ProviderSelector';
import { BulkWarning } from './BulkWarning';

/**
 * Select source folders, pick a tested template and a provider, review, start.
 *
 * Folders are chosen by NAME from the backend's listing of BULK_IMPORT_ROOT's
 * immediate subfolders — the browser never sees or sends a filesystem path, and
 * the ~14,000 images never traverse it either.
 */
export const BulkStartStep: React.FC = () => {
  const {
    selectedFolders,
    toggleFolder,
    setSelectedFolders,
    templateId,
    setTemplateId,
    runName,
    setRunName,
    provider,
    setProvider,
    model,
    setModel,
    setRunId,
    setStep,
  } = useBulkStore();

  const sources = useBulkSourcesQuery(true);
  const templates = useTemplatesQuery();
  const runs = useBulkRunsQuery(true);
  const createRun = useCreateBulkRunMutation();
  const startRun = useStartBulkRunMutation();

  // Memoised so the derived useMemo below does not re-run on every render.
  const folders = useMemo(() => sources.data?.folders ?? [], [sources.data]);
  const template = templates.data?.find((t) => t.id === templateId) ?? null;

  const selectedImages = useMemo(
    () =>
      folders
        .filter((f) => selectedFolders.includes(f.name))
        .reduce((sum, f) => sum + f.images_total, 0),
    [folders, selectedFolders]
  );

  // A run left paused or interrupted by a restart must be easy to find again.
  const openRuns = (runs.data ?? []).filter((r) => isResumable(r.status) && r.status !== 'queued');

  const allSelected = folders.length > 0 && selectedFolders.length === folders.length;
  const canStart =
    selectedFolders.length > 0 && !!template && !!runName.trim() && !createRun.isPending;

  const handleStart = async () => {
    if (!template) return;
    // Preserve the picker's click order, but list folders in the listing's
    // order so processing (and therefore the CSV) is predictable.
    const ordered = folders.map((f) => f.name).filter((n) => selectedFolders.includes(n));
    const run = await createRun.mutateAsync({
      name: runName.trim(),
      template_id: template.id,
      folders: ordered,
      provider,
      model: model || null,
    });
    setRunId(run.bulk_run_id);
    setStep('progress');
    await startRun.mutateAsync(run.bulk_run_id);
    toast.success(`Bulk run started: ${run.folders_total} folders, ${run.images_total} images`);
  };

  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <h2 className="font-serif text-2xl text-archive-ink">Bulk / Multi-Batch Processing</h2>
        <p className="text-sm text-archive-ink/60 leading-relaxed max-w-3xl">
          Process many source folders sequentially with one already-tested
          extraction template, then download a single CSV that keeps each
          record&rsquo;s source folder and filename.
        </p>
      </header>

      <BulkWarning />

      {openRuns.length > 0 && (
        <section className="space-y-2">
          <h3 className="text-xs uppercase tracking-widest text-archive-sepia/60 font-semibold">
            Unfinished runs
          </h3>
          <div className="space-y-2">
            {openRuns.map((run) => (
              <button
                key={run.bulk_run_id}
                onClick={() => {
                  setRunId(run.bulk_run_id);
                  setStep('progress');
                }}
                className="w-full flex items-center justify-between gap-4 p-3 rounded border border-parchment-dark/60 hover:border-archive-sepia/50 text-left transition-colors"
              >
                <span className="font-serif text-archive-ink">{run.name}</span>
                <span className="text-xs font-mono text-archive-ink/50">
                  {run.status} · {run.folders_completed}/{run.folders_total} folders
                </span>
              </button>
            ))}
          </div>
        </section>
      )}

      {/* ── Source folders ─────────────────────────────────────────────── */}
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <label className="text-xs uppercase tracking-widest text-archive-ink/40 font-semibold flex items-center gap-2">
            <FolderTree className="w-3 h-3" />
            Source folders
          </label>
          <div className="flex items-center gap-3">
            <button
              onClick={() => setSelectedFolders(allSelected ? [] : folders.map((f) => f.name))}
              className="text-xs text-archive-sepia hover:underline"
            >
              {allSelected ? 'Clear selection' : 'Select all'}
            </button>
            <button
              onClick={() => sources.refetch()}
              className="text-xs text-archive-ink/50 hover:text-archive-ink flex items-center gap-1"
            >
              <RefreshCw className="w-3 h-3" />
              Refresh
            </button>
          </div>
        </div>

        {sources.isLoading ? (
          <div className="flex items-center gap-2 text-archive-ink/40 text-sm italic py-2">
            <Loader2 className="w-4 h-4 animate-spin" />
            Reading the import directory&hellip;
          </div>
        ) : folders.length === 0 ? (
          <p className="text-sm text-archive-ink/50 italic">
            The configured import directory has no subfolders containing supported images.
          </p>
        ) : (
          <>
            <div className="max-h-72 overflow-y-auto rounded border border-parchment-dark/60 divide-y divide-parchment-dark/40">
              {folders.map((folder) => {
                const checked = selectedFolders.includes(folder.name);
                return (
                  <label
                    key={folder.name}
                    className={`flex items-center gap-3 px-3 py-2 cursor-pointer transition-colors ${
                      checked ? 'bg-archive-sepia/5' : 'hover:bg-parchment-dark/20'
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggleFolder(folder.name)}
                      className="sr-only"
                    />
                    {checked ? (
                      <CheckSquare className="w-4 h-4 text-archive-sepia shrink-0" />
                    ) : (
                      <Square className="w-4 h-4 text-archive-ink/30 shrink-0" />
                    )}
                    <span className="font-mono text-sm text-archive-ink flex-1 truncate">
                      {folder.name}
                    </span>
                    <span className="text-xs text-archive-ink/50 tabular-nums">
                      {folder.images_total.toLocaleString()} images
                    </span>
                  </label>
                );
              })}
            </div>
            {sources.data?.truncated && (
              <p className="text-xs text-amber-700/80">
                Only the first folders of the import directory are shown. Raise
                BULK_MAX_FOLDERS to list more.
              </p>
            )}
          </>
        )}
      </section>

      {/* ── Template ───────────────────────────────────────────────────── */}
      <section className="space-y-2">
        <label className="text-xs uppercase tracking-widest text-archive-ink/40 font-semibold flex items-center gap-2">
          <LayoutGrid className="w-3 h-3" />
          Extraction template
        </label>
        <select
          value={templateId ?? ''}
          onChange={(e) => setTemplateId(e.target.value || null)}
          className="w-full bg-parchment-light/30 border border-parchment-dark/50 rounded px-3 py-2 text-sm text-archive-ink focus:outline-none focus:border-archive-sepia/50 cursor-pointer"
        >
          <option value="">Select a template&hellip;</option>
          {(templates.data ?? []).map((t) => (
            <option key={t.id} value={t.id}>
              {t.name} — {t.fields.length} fields
            </option>
          ))}
        </select>
        {template && (
          <p className="text-xs font-mono text-archive-ink/50 truncate">
            {template.fields.join(' · ')}
          </p>
        )}
        {templates.data?.length === 0 && (
          <p className="text-xs text-amber-700/80">
            No templates yet. Create and test one in the standard batch workflow first.
          </p>
        )}
      </section>

      {/* ── Provider / model ───────────────────────────────────────────── */}
      <section>
        <ProviderSelector
          value={provider}
          model={model}
          onProviderChange={setProvider}
          onModelChange={setModel}
        />
      </section>

      {/* ── Run name ───────────────────────────────────────────────────── */}
      <section className="space-y-2">
        <label className="text-xs uppercase tracking-widest text-archive-ink/40 font-semibold">
          Run name
        </label>
        <input
          type="text"
          value={runName}
          onChange={(e) => setRunName(e.target.value)}
          placeholder="e.g. AMIGA Tonbandkartei"
          className="w-full bg-parchment-light/30 border border-parchment-dark/50 rounded px-3 py-2 text-sm text-archive-ink focus:outline-none focus:border-archive-sepia/50"
        />
        <p className="text-xs text-archive-ink/40">
          A label for this run and its download. It is never used as a file path.
        </p>
      </section>

      {/* ── Review ─────────────────────────────────────────────────────── */}
      <section className="p-4 rounded border border-parchment-dark/60 bg-parchment-light/20 space-y-2">
        <h3 className="text-xs uppercase tracking-widest text-archive-sepia/60 font-semibold">
          Review
        </h3>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
          <dt className="text-archive-ink/50">Folders</dt>
          <dd className="text-archive-ink tabular-nums">{selectedFolders.length}</dd>
          <dt className="text-archive-ink/50">Images</dt>
          <dd className="text-archive-ink tabular-nums">
            ~{selectedImages.toLocaleString()}
          </dd>
          <dt className="text-archive-ink/50">Template</dt>
          <dd className="text-archive-ink">{template?.name ?? '—'}</dd>
          <dt className="text-archive-ink/50">Model</dt>
          <dd className="text-archive-ink font-mono text-xs truncate">{model || '—'}</dd>
          <dt className="text-archive-ink/50">Processing</dt>
          <dd className="text-archive-ink">Sequential, one folder at a time</dd>
          <dt className="text-archive-ink/50">Intermediate QC</dt>
          <dd className="text-archive-ink">Skipped</dd>
        </dl>
      </section>

      <div className="flex justify-end">
        <button
          onClick={handleStart}
          disabled={!canStart}
          className="flex items-center gap-2 px-6 py-3 rounded bg-archive-sepia text-parchment font-medium disabled:opacity-40 disabled:cursor-not-allowed hover:bg-archive-sepia/90 transition-colors"
        >
          {createRun.isPending ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Play className="w-4 h-4" />
          )}
          Start bulk run
        </button>
      </div>
    </div>
  );
};
