import React from 'react';
import { Cpu, AlertTriangle } from 'lucide-react';
import { useWizardStore, type OcrProvider } from '../../store/wizardStore';
import { useAppConfigQuery, useOllamaModelsQuery } from '../../api/configApi';

interface ModelOption {
  value: string;
  label: string;
  description: string;
}

// OpenRouter models are a curated cloud catalogue — safe to keep static in the bundle.
const OPENROUTER_MODELS: ModelOption[] = [
  { value: 'qwen/qwen3-vl-8b-instruct',                 label: 'Qwen3-VL 8B',           description: 'Qwen · Standard' },
  { value: 'qwen/qwen2.5-vl-72b-instruct',              label: 'Qwen2.5-VL 72B',        description: 'Qwen · Leistungsstark' },
  { value: 'anthropic/claude-opus-4',                   label: 'Claude Opus 4',         description: 'Anthropic · Spitzenmodell' },
  { value: 'anthropic/claude-sonnet-4-5',               label: 'Claude Sonnet 4.5',     description: 'Anthropic · Ausgewogen' },
  { value: 'openai/gpt-4o',                             label: 'GPT-4o',                description: 'OpenAI · Multimodal' },
  { value: 'google/gemini-2.5-pro-preview',             label: 'Gemini 2.5 Pro',        description: 'Google · Spitzenmodell' },
  { value: 'google/gemini-2.0-flash-001',               label: 'Gemini 2.0 Flash',      description: 'Google · Schnell' },
  { value: 'meta-llama/llama-3.2-90b-vision-instruct',  label: 'LLaMA 3.2 Vision 90B', description: 'Meta · Open Source' },
  { value: 'mistralai/pixtral-large-2411',              label: 'Pixtral Large',         description: 'Mistral · Multimodal' },
  { value: 'microsoft/phi-4-multimodal-instruct',       label: 'Phi-4 Multimodal',      description: 'Microsoft · Kompakt' },
];

export const ProviderSelector: React.FC = () => {
  const { provider, model, setProvider, setModel } = useWizardStore();

  // Runtime config drives provider labels/hints/defaults so a new institution can
  // point at their own Ollama instance by editing the backend .env — no rebuild.
  const { data: appConfig } = useAppConfigQuery();
  const ollamaModelsQuery = useOllamaModelsQuery(provider === 'ollama');

  const providers = (appConfig?.providers ?? []).filter((p) => p.enabled);
  const defaultModelFor = (value: string) =>
    providers.find((p) => p.value === value)?.default_model ?? '';

  const handleProviderChange = (newProvider: OcrProvider) => {
    setProvider(newProvider);
    setModel(defaultModelFor(newProvider));
  };

  const isOllama = provider === 'ollama';
  const ollamaData = ollamaModelsQuery.data;
  const ollamaReachable = ollamaData?.reachable ?? false;

  // OpenRouter → static catalogue. Ollama → live list from the server (via backend).
  const models: ModelOption[] = isOllama
    ? (ollamaData?.models ?? [])
    : OPENROUTER_MODELS;

  // When the Ollama server is unreachable (or lists nothing), fall back to a
  // free-text model field so the curator can still enter a known model id.
  const showFreeText = isOllama && (!ollamaReachable || models.length === 0);

  return (
    <div className="flex flex-col gap-3">
      <label className="text-xs uppercase tracking-widest text-archive-ink/40 font-semibold flex items-center gap-2">
        <Cpu className="w-3 h-3" />
        OCR-Anbieter &amp; Modell
      </label>

      <div className="flex flex-col gap-2">
        {providers.map((p) => (
          <label
            key={p.value}
            className={`flex items-start gap-3 p-3 rounded border cursor-pointer transition-colors ${
              provider === p.value
                ? 'border-archive-sepia/60 bg-archive-sepia/5'
                : 'border-parchment-dark/50 hover:border-archive-sepia/30'
            }`}
          >
            <input
              type="radio"
              name="provider"
              value={p.value}
              checked={provider === p.value}
              onChange={() => handleProviderChange(p.value as OcrProvider)}
              className="mt-0.5 accent-archive-sepia"
            />
            <div>
              <p className="text-sm font-serif text-archive-ink font-semibold">{p.label}</p>
              <p className="text-xs text-archive-ink/50 font-mono">{p.endpoint_hint}</p>
            </div>
          </label>
        ))}
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-xs text-archive-ink/40 uppercase tracking-widest">Modell</label>

        {showFreeText ? (
          <>
            <input
              type="text"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="z.B. qwen3-vl:235b"
              className="w-full bg-parchment-light/30 border border-parchment-dark/50 rounded px-3 py-2 text-sm font-mono text-archive-ink focus:outline-none focus:border-archive-sepia/50 transition-colors"
            />
            {isOllama && ollamaModelsQuery.isFetched && !ollamaReachable && (
              <p className="text-xs text-amber-700/80 font-mono flex items-center gap-1 mt-0.5">
                <AlertTriangle className="w-3 h-3 shrink-0" />
                {ollamaData?.error ?? 'Ollama-Server nicht erreichbar — Modell manuell eingeben.'}
              </p>
            )}
          </>
        ) : (
          <select
            value={model}
            onChange={(e) => setModel(e.target.value)}
            className="w-full bg-parchment-light/30 border border-parchment-dark/50 rounded px-3 py-2 text-sm font-mono text-archive-ink focus:outline-none focus:border-archive-sepia/50 transition-colors cursor-pointer"
          >
            {models.map((m) => (
              <option key={m.value} value={m.value}>
                {m.description ? `${m.label} — ${m.description}` : m.label}
              </option>
            ))}
          </select>
        )}

        <p className="text-xs text-archive-ink/40 font-mono truncate">{model}</p>
      </div>
    </div>
  );
};
