import axios from 'axios';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import type { ExtractionResult } from '../store/wizardStore';

export interface FieldRule {
  preset_id?: string | null;
  pattern?: string | null;
  vocabulary?: string[] | null;
  fuzzy_distance?: number | null;
  corrector_enabled?: boolean;
}

export interface ReconciliationOutcome {
  authority: string;
  uri: string;
  label: string;
  picked_by: 'auto' | 'manual';
  picked_at: string;
}

export type AuthorityType =
  | 'gnd-persons'
  | 'gnd-places'
  | 'gnd-subjects'
  | 'gnd-corporate-bodies'
  | 'gnd-works'
  | 'wikidata'
  | 'geonames'
  | 'aat'
  | null;

export interface AuthorityBinding {
  type: AuthorityType;
}

export interface ValidationOutcome {
  status: 'valid' | 'invalid' | 'corrected' | 'skipped' | 'verified';
  rule_failed?: string | null;
  original_value?: string | null;
  rationale?: string | null;
  corrector_proposal?: string | null;
  reconciliation?: ReconciliationOutcome | null;  // Phase 11 — independent of status dimension
}

export interface BatchCreate {
  custom_name: string;
  session_id: string;
  fields: string[];
  prompt_template?: string | null;
  field_rules?: Record<string, FieldRule> | null;
  corrector_enabled?: boolean;
  corrector_cap?: number | null;
  authority_bindings?: Record<string, AuthorityBinding> | null;  // Phase 11
  describe_pictures?: boolean;  // opt-in picture description
}

export interface BatchResponse {
  batch_name: string;
  status: string;
  files_count: number;
}

export interface AuditEntry {
  id: string;
  ts: string;
  op: 'bulk-transform' | 'cluster-merge' | 'reconciliation';  // Phase 11 added 'reconciliation'
  column: string;
  label: string;
  affected: number;
  scope: 'all' | 'faceted';
  facet_description?: string | null;
  source: 'bulk-transform' | 'cluster-merge' | 'reconciliation-auto' | 'reconciliation-manual' | 'reconciliation-cleared-by-edit' | 'reconciliation-no-match';  // Phase 11 added 4 reconciliation values
}

export interface BatchConfig {
  fields: string[];
  field_rules: Record<string, FieldRule> | null;
  authority_bindings?: Record<string, AuthorityBinding> | null;  // Phase 11
}

export interface BatchHistoryItem {
  batch_name: string;
  custom_name: string;
  created_at: string;
  status: string;
  files_count: number;
  fields: string[];
  has_errors: boolean;
  error_count: number;
}

const createBatch = async (data: BatchCreate): Promise<BatchResponse> => {
  const response = await axios.post<BatchResponse>('/api/v1/batches/', data);
  return response.data;
};

const startBatch = async ({
  batchName,
  provider = 'openrouter',
  model,
}: {
  batchName: string;
  provider?: string;
  model?: string;
}): Promise<{ message: string; batch_name: string }> => {
  const response = await axios.post<{ message: string; batch_name: string }>(
    `/api/v1/batches/${batchName}/start`,
    { provider, ...(model ? { model } : {}) }
  );
  return response.data;
};

export const cancelBatch = async (batchName: string): Promise<{ message: string; batch_name: string }> => {
  const response = await axios.post<{ message: string; batch_name: string }>(`/api/v1/batches/${batchName}/cancel`);
  return response.data;
};

export const fetchResults = async (batchName: string): Promise<{ results: ExtractionResult[]; audit: AuditEntry[] }> => {
  const response = await axios.get<{ results: ExtractionResult[]; audit: AuditEntry[] }>(
    `/api/v1/batches/${batchName}/results`
  );
  return response.data;
};

export async function patchResult(
  batchName: string,
  filename: string,
  patch: {
    field: string;
    value?: string | null;
    validation_status?: string | null;
    reconciliation?: ReconciliationOutcome;    // Phase 11: set a new outcome (omit to leave alone)
    clear_reconciliation?: boolean;             // Phase 11: true → clear existing reconciliation
    audit_entry?: AuditEntry | null;
  }
): Promise<void> {
  await axios.patch(
    `/api/v1/batches/${batchName}/results/${encodeURIComponent(filename)}`,
    patch
  );
}

export async function fetchBatchConfig(batchName: string): Promise<BatchConfig> {
  const response = await axios.get<BatchConfig>(`/api/v1/batches/${batchName}/config`);
  return response.data;
}

export interface ReconcileCandidate {
  label: string;
  uri: string;
  description: string;
}

export async function postReconcile(
  batchName: string,
  authority: AuthorityType,
  query: string
): Promise<{ candidates: ReconcileCandidate[]; from_cache: boolean }> {
  const response = await axios.post('/api/v1/reconcile', {
    authority,
    query,
    batch_name: batchName,
  });
  return response.data;
}

/** Report an export lifecycle event so the backend can audit it and (for a final
 *  METS/MODS ingest export) optionally purge working data. Best-effort: never
 *  blocks or fails the actual client-side download. */
export async function reportExportEvent(
  batchName: string,
  event: { format: string; phase?: 'started' | 'completed'; is_final_ingest?: boolean }
): Promise<void> {
  try {
    await axios.post(`/api/v1/batches/${encodeURIComponent(batchName)}/export-event`, {
      format: event.format,
      phase: event.phase ?? 'completed',
      is_final_ingest: event.is_final_ingest ?? false,
    });
  } catch {
    // Auditing must not break the download; swallow errors silently.
  }
}

export const retryImage = async (batchName: string, filename: string): Promise<{ message: string }> => {
  const response = await axios.post<{ message: string }>(`/api/v1/batches/${batchName}/retry-image/${filename}`);
  return response.data;
};

export const retryBatch = async (batchName: string): Promise<{ message: string; batch_name: string }> => {
  const response = await axios.post<{ message: string; batch_name: string }>(`/api/v1/batches/${batchName}/retry`);
  return response.data;
};

export const useCreateBatchMutation = () => {
  return useMutation({
    mutationFn: createBatch,
    onSuccess: (data) => {
      toast.success(`Batch "${data.batch_name}" created successfully.`);
    },
    onError: (error: Error & { response?: { data?: { detail?: string } } }) => {
      const errorMessage = error.response?.data?.detail || 'Failed to create batch.';
      toast.error(errorMessage);
    },
  });
};

export const useStartBatchMutation = () => {
  return useMutation({
    mutationFn: startBatch,
    onSuccess: (data) => {
      toast.success(`Processing started for ${data.batch_name}.`);
    },
    onError: (error: Error & { response?: { data?: { detail?: string } } }) => {
      const errorMessage = error.response?.data?.detail || 'Failed to start processing.';
      toast.error(errorMessage);
    },
  });
};

export const useCancelBatchMutation = () => {
  return useMutation({
    mutationFn: cancelBatch,
    onError: (error: Error & { response?: { data?: { detail?: string } } }) => {
      const errorMessage = error.response?.data?.detail || 'Failed to cancel batch.';
      toast.error(errorMessage);
    },
  });
};

export const useRetryImageMutation = () => {
  return useMutation({
    mutationFn: ({ batchName, filename }: { batchName: string; filename: string }) =>
      retryImage(batchName, filename),
    onSuccess: () => {
      toast.success('Image queued for retry.');
    },
    onError: (error: Error & { response?: { data?: { detail?: string } } }) => {
      const errorMessage = error.response?.data?.detail || 'Failed to retry image.';
      toast.error(errorMessage);
    },
  });
};

export const useRetryBatchMutation = () => {
  return useMutation({
    mutationFn: retryBatch,
    onSuccess: (data) => {
      toast.success(`Retry started for ${data.batch_name}.`);
    },
    onError: (error: Error & { response?: { data?: { detail?: string } } }) => {
      const errorMessage = error.response?.data?.detail || 'Failed to retry batch.';
      toast.error(errorMessage);
    },
  });
};

export const useResultsQuery = (batchName: string | null) => {
  return useQuery({
    queryKey: ['results', batchName],
    queryFn: () => fetchResults(batchName!),
    enabled: !!batchName,
    select: (data) => data.results,  // Exposes ExtractionResult[] — keeps existing callers unchanged
  });
};

/** Returns the full {results, audit} shape — used by CleanStep to hydrate AuditPanel on entry. */
export const useBatchResultsRawQuery = (batchName: string | null) => {
  return useQuery({
    queryKey: ['results', batchName],
    queryFn: () => fetchResults(batchName!),
    enabled: !!batchName,
  });
};

export function useBatchConfigQuery(batchName: string | null) {
  return useQuery({
    queryKey: ['batchConfig', batchName],
    queryFn: () => fetchBatchConfig(batchName!),
    enabled: !!batchName,
    staleTime: Infinity,  // Config doesn't change after batch creation
  });
}

const fetchBatchHistory = async (): Promise<BatchHistoryItem[]> => {
  const response = await axios.get<BatchHistoryItem[]>('/api/v1/batches/history');
  return response.data;
};

const deleteBatch = async (batchName: string): Promise<void> => {
  await axios.delete(`/api/v1/batches/${batchName}`);
};

export const useBatchHistoryQuery = () => {
  return useQuery({
    queryKey: ['batch-history'],
    queryFn: fetchBatchHistory,
  });
};

export const useDeleteBatchMutation = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteBatch,
    onSuccess: () => {
      toast.success('Batch deleted');
      queryClient.invalidateQueries({ queryKey: ['batch-history'] });
    },
    onError: (error: Error & { response?: { data?: { detail?: string } } }) => {
      const errorMessage = error.response?.data?.detail || 'Failed to delete batch.';
      toast.error(errorMessage);
    },
  });
};
