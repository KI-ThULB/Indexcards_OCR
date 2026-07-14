import axios from 'axios';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import type { FieldRule, AuthorityBinding } from './batchesApi';
export type { FieldRule, AuthorityBinding };

export interface Template {
  id: string;
  name: string;
  fields: string[];
  prompt_template?: string | null;
  field_rules?: Record<string, FieldRule> | null;
  authority_bindings?: Record<string, AuthorityBinding> | null;  // Phase 11
}

const fetchTemplates = async (): Promise<Template[]> => {
  const response = await axios.get<Template[]>('/api/v1/templates/');
  return response.data;
};

export const useTemplatesQuery = () => {
  return useQuery({
    queryKey: ['templates'],
    queryFn: fetchTemplates,
  });
};

export const useCreateTemplateMutation = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (data: { name: string; fields: string[]; prompt_template?: string | null; field_rules?: Record<string, FieldRule> | null; authority_bindings?: Record<string, AuthorityBinding> | null }) => {
      const response = await axios.post<Template>('/api/v1/templates/', data);
      return response.data;
    },
    onSuccess: () => {
      toast.success('Template saved');
      queryClient.invalidateQueries({ queryKey: ['templates'] });
    },
    onError: (error: unknown) => {
      const axiosError = error as { response?: { data?: { detail?: string } }; message?: string };
      const message = axiosError.response?.data?.detail ?? axiosError.message ?? 'Failed to save template';
      toast.error(message);
    },
  });
};

export const useUpdateTemplateMutation = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (data: { id: string; name?: string; fields?: string[]; prompt_template?: string | null; field_rules?: Record<string, FieldRule> | null; authority_bindings?: Record<string, AuthorityBinding> | null }) => {
      const { id, ...body } = data;
      const response = await axios.put<Template>(`/api/v1/templates/${id}`, body);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['templates'] });
    },
    onError: (error: unknown) => {
      const axiosError = error as { response?: { data?: { detail?: string } }; message?: string };
      const message = axiosError.response?.data?.detail ?? axiosError.message ?? 'Failed to update template';
      toast.error(message);
    },
  });
};

export const useDeleteTemplateMutation = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      await axios.delete(`/api/v1/templates/${id}`);
    },
    onSuccess: () => {
      toast.success('Template deleted');
      queryClient.invalidateQueries({ queryKey: ['templates'] });
    },
    onError: (error: unknown) => {
      const axiosError = error as { response?: { data?: { detail?: string } }; message?: string };
      const message = axiosError.response?.data?.detail ?? axiosError.message ?? 'Failed to delete template';
      toast.error(message);
    },
  });
};
