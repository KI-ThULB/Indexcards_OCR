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

export interface ValidationOutcome {
  status: 'valid' | 'invalid' | 'corrected' | 'skipped';
  rule_failed?: string | null;
  original_value?: string | null;
  rationale?: string | null;
  corrector_proposal?: string | null;
}

export interface BatchCreate {
  custom_name: string;
  session_id: string;
  fields: string[];
  prompt_template?: string | null;
  field_rules?: Record<string, FieldRule> | null;
  corrector_enabled?: boolean;
  corrector_cap?: number | null;
}

export interface BatchResponse {
  batch_name: string;
  status: string;
  files_count: number;
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

export const fetchResults = async (batchName: string): Promise<ExtractionResult[]> => {
  const response = await axios.get<ExtractionResult[]>(`/api/v1/batches/${batchName}/results`);
  return response.data;
};

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
  });
};

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
