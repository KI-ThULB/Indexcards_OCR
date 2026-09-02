import axios from 'axios';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

// react-query hooks over the /api/v1/bulk surface. The bearer token (when one
// is configured) is inherited from api/client.ts's axios defaults, so nothing
// auth-related is duplicated here.
//
// While BULK_IMPORT_ROOT is unset every route 404s, which is why the UI gates
// the whole feature on config.bulk_enabled rather than probing these endpoints.

export type BulkRunStatus =
  | 'queued'
  | 'running'
  | 'paused'
  | 'interrupted'
  | 'completed'
  | 'completed_with_errors'
  | 'failed'
  | 'cancelled';

export type BulkFolderStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'completed_with_errors'
  | 'failed'
  | 'skipped';

export interface BulkSourceFolder {
  name: string;
  images_total: number;
}

export interface BulkSourcesResponse {
  root_configured: boolean;
  folders: BulkSourceFolder[];
  truncated: boolean;
}

export interface BulkFolderProgress {
  source_folder: string;
  batch_name?: string | null;
  status: BulkFolderStatus;
  images_total: number;
  images_processed: number;
  images_failed: number;
  started_at?: string | null;
  completed_at?: string | null;
  error?: string | null;
}

/** Live state of a bulk run. Carries no extracted metadata — counts only. */
export interface BulkProgress {
  bulk_run_id: string;
  name: string;
  status: BulkRunStatus;
  provider: string;
  model?: string | null;
  folders_total: number;
  folders_completed: number;
  images_total: number;
  images_processed: number;
  images_failed: number;
  current_folder?: string | null;
  current_batch_id?: string | null;
  last_image?: string | null;
  created_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  interrupted_at?: string | null;
  error?: string | null;
  pause_requested: boolean;
  cancel_requested: boolean;
  schema_fields: string[];
  folders: BulkFolderProgress[];
}

export interface BulkRunCreate {
  name: string;
  template_id: string;
  folders: string[];
  provider: string;
  model?: string | null;
}

const TERMINAL: BulkRunStatus[] = [
  'completed',
  'completed_with_errors',
  'failed',
  'cancelled',
];

export const isTerminal = (status: BulkRunStatus) => TERMINAL.includes(status);
export const isResumable = (status: BulkRunStatus) =>
  status === 'paused' || status === 'interrupted' || status === 'queued';

function errorMessage(error: unknown, fallback: string): string {
  const e = error as { response?: { data?: { detail?: string } }; message?: string };
  return e.response?.data?.detail ?? e.message ?? fallback;
}

// ── Queries ──────────────────────────────────────────────────────────────────

export const useBulkSourcesQuery = (enabled: boolean) =>
  useQuery({
    queryKey: ['bulk-sources'],
    queryFn: async () => {
      const { data } = await axios.get<BulkSourcesResponse>('/api/v1/bulk/sources');
      return data;
    },
    enabled,
    staleTime: 30 * 1000,
  });

export const useBulkRunsQuery = (enabled: boolean) =>
  useQuery({
    queryKey: ['bulk-runs'],
    queryFn: async () => {
      const { data } = await axios.get<BulkProgress[]>('/api/v1/bulk/runs');
      return data;
    },
    enabled,
  });

/**
 * One run's state. The WebSocket carries live updates, so this is mainly the
 * initial load and the safety net after a reconnect. `refetchInterval` keeps a
 * running job's numbers moving even if the socket is unavailable.
 */
export const useBulkRunQuery = (bulkRunId: string | null) =>
  useQuery({
    queryKey: ['bulk-run', bulkRunId],
    queryFn: async () => {
      const { data } = await axios.get<BulkProgress>(`/api/v1/bulk/runs/${bulkRunId}`);
      return data;
    },
    enabled: !!bulkRunId,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && isTerminal(status) ? false : 5000;
    },
  });

// ── Mutations ────────────────────────────────────────────────────────────────

export const useCreateBulkRunMutation = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: BulkRunCreate) => {
      const { data } = await axios.post<BulkProgress>('/api/v1/bulk/runs', body);
      return data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['bulk-runs'] }),
    onError: (error) => toast.error(errorMessage(error, 'Could not create the bulk run')),
  });
};

function useRunAction(action: 'start' | 'resume' | 'pause' | 'cancel', fallback: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (bulkRunId: string) => {
      const { data } = await axios.post<BulkProgress>(
        `/api/v1/bulk/runs/${bulkRunId}/${action}`
      );
      return data;
    },
    onSuccess: (data) => {
      queryClient.setQueryData(['bulk-run', data.bulk_run_id], data);
      queryClient.invalidateQueries({ queryKey: ['bulk-runs'] });
    },
    onError: (error) => toast.error(errorMessage(error, fallback)),
  });
}

export const useStartBulkRunMutation = () => useRunAction('start', 'Could not start the run');
export const useResumeBulkRunMutation = () => useRunAction('resume', 'Could not resume the run');
export const usePauseBulkRunMutation = () => useRunAction('pause', 'Could not pause the run');
export const useCancelBulkRunMutation = () => useRunAction('cancel', 'Could not cancel the run');

// ── Downloads ────────────────────────────────────────────────────────────────

/**
 * Download a generated CSV.
 *
 * Fetched through axios rather than a plain link so the bearer token is sent
 * when one is configured; the blob is then handed to the browser.
 */
async function downloadCsv(url: string, filename: string) {
  const response = await axios.get(url, { responseType: 'blob' });
  const href = URL.createObjectURL(response.data as Blob);
  const anchor = document.createElement('a');
  anchor.href = href;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(href);
}

const safeFilename = (name: string) =>
  name.replace(/[^A-Za-z0-9-_]+/g, '_').replace(/^_+|_+$/g, '') || 'bulk_run';

export async function downloadConsolidatedCsv(run: BulkProgress) {
  try {
    await downloadCsv(
      `/api/v1/bulk/runs/${run.bulk_run_id}/export.csv`,
      `${safeFilename(run.name)}_consolidated.csv`
    );
  } catch (error) {
    toast.error(errorMessage(error, 'Could not download the consolidated CSV'));
  }
}

export async function downloadFailuresCsv(run: BulkProgress) {
  try {
    await downloadCsv(
      `/api/v1/bulk/runs/${run.bulk_run_id}/failures.csv`,
      `${safeFilename(run.name)}_failures.csv`
    );
  } catch (error) {
    toast.error(errorMessage(error, 'Could not download the failed-records CSV'));
  }
}
