import axios from 'axios';
import { useQuery } from '@tanstack/react-query';

// Runtime, non-sensitive configuration served by the backend (GET /api/v1/config).
// Lets the same built frontend be pointed at a different Ollama instance by editing
// the backend .env only — no rebuild. Contains NO base URLs and NO credentials.

export interface ProviderInfo {
  value: string;           // "openrouter" | "ollama"
  label: string;
  endpoint_hint: string;   // cosmetic only — never the real URL
  default_model: string;
  enabled: boolean;
}

export interface AppConfig {
  providers: ProviderInfo[];
}

export interface OllamaModel {
  value: string;
  label: string;
  description: string;
}

export interface OllamaModelsResponse {
  models: OllamaModel[];
  reachable: boolean;
  error?: string | null;
}

const fetchAppConfig = async (): Promise<AppConfig> => {
  const response = await axios.get<AppConfig>('/api/v1/config');
  return response.data;
};

const fetchOllamaModels = async (): Promise<OllamaModelsResponse> => {
  // The backend queries Ollama server-side; the browser never contacts Ollama directly.
  const response = await axios.get<OllamaModelsResponse>('/api/v1/config/ollama/models');
  return response.data;
};

export const useAppConfigQuery = () => {
  return useQuery({
    queryKey: ['app-config'],
    queryFn: fetchAppConfig,
    staleTime: Infinity, // runtime config is fixed for the life of the backend process
  });
};

export const useOllamaModelsQuery = (enabled: boolean) => {
  return useQuery({
    queryKey: ['ollama-models'],
    queryFn: fetchOllamaModels,
    enabled,
    staleTime: 5 * 60 * 1000, // 5 min — installed models change rarely
    retry: false,             // a connection failure is reported in-band (reachable:false)
  });
};
