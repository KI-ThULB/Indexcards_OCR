import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { FieldRule, ValidationOutcome, AuthorityBinding } from '../api/batchesApi';
export type { FieldRule, ValidationOutcome, AuthorityBinding };

export type WizardStep = 'upload' | 'configure' | 'processing' | 'results' | 'verify' | 'clean';
export type AppView = 'wizard' | 'history';

export interface UploadedFile {
  id: string;
  name: string;
  size: number;
  type: string;
  preview?: string;
}

export interface MetadataField {
  id: string;
  label: string;
  type: 'text' | 'date' | 'number' | 'enum';
  options?: string[];
  rule?: FieldRule | null;           // Phase 8
  authority?: AuthorityBinding | null;  // Phase 11 — authority reconciliation binding
}

export interface ExtractionResult {
  filename: string;
  batch: string;
  success: boolean;
  data: Record<string, string> | null;
  error?: string | null;
  duration: number;
  validation?: Record<string, ValidationOutcome | null> | null;
  edited_data?: Record<string, string> | null;  // Phase 9 PATCH writes curator edits; Phase 12 adds round-trip read from /results
  confidence?: Record<string, number> | null;    // per-field VLM self-confidence 0–1
  confidence_overall?: number | null;             // card-level VLM self-confidence 0–1
}

export interface BatchProgress {
  batch_name: string;
  current: number;
  total: number;
  percentage: number;
  eta_seconds: number | null;
  last_result: ExtractionResult | null;
  status: 'running' | 'completed' | 'failed' | 'retrying' | 'cancelled';
  error?: string | null;
}

export interface ResultRow {
  filename: string;
  status: 'success' | 'failed';
  error?: string;
  data: Record<string, string>;
  editedData: Record<string, string>;
  duration: number;
  validation?: Record<string, ValidationOutcome | null> | null;
  confidence?: Record<string, number> | null;    // per-field VLM self-confidence 0–1
  confidenceOverall?: number | null;              // card-level VLM self-confidence 0–1
}

export interface ProcessingState {
  consecutiveFailures: number;
  liveFeedItems: ExtractionResult[];
  lastProgress: BatchProgress | null;
  isCancelled: boolean;
  isProcessing: boolean;
}

const initialProcessingState: ProcessingState = {
  consecutiveFailures: 0,
  liveFeedItems: [],
  lastProgress: null,
  isCancelled: false,
  isProcessing: false,
};

export type OcrProvider = 'openrouter' | 'ollama';

export const PROVIDER_DEFAULT_MODELS: Record<OcrProvider, string> = {
  openrouter: 'qwen/qwen3-vl-8b-instruct',
  ollama: 'qwen3-vl:235b',
};

interface WizardState {
  step: WizardStep;
  view: AppView;
  files: UploadedFile[];
  fields: MetadataField[];
  sessionId: string | null;
  batchId: string | null;
  promptTemplate: string | null;
  provider: OcrProvider;
  model: string;
  correctorEnabled: boolean;
  correctorCap: number;
  describePictures: boolean;
  processingState: ProcessingState;
  results: ResultRow[];
  setStep: (step: WizardStep) => void;
  setView: (view: AppView) => void;
  setSessionId: (id: string | null) => void;
  resetWizard: () => void;
  updateFiles: (files: UploadedFile[]) => void;
  setBatchId: (id: string | null) => void;
  setFields: (fields: MetadataField[]) => void;
  setPromptTemplate: (t: string | null) => void;
  selectedTemplateName: string | null;
  setSelectedTemplateName: (name: string | null) => void;
  setProvider: (provider: OcrProvider) => void;
  setModel: (model: string) => void;
  removeFile: (id: string) => void;
  clearFiles: () => void;
  appendLiveFeedItem: (item: ExtractionResult) => void;
  setLastProgress: (p: BatchProgress) => void;
  incrementConsecutiveFailures: () => void;
  resetConsecutiveFailures: () => void;
  setCancelled: (cancelled: boolean) => void;
  setIsProcessing: (processing: boolean) => void;
  setResults: (rows: ResultRow[]) => void;
  updateResultCell: (filename: string, field: string, value: string) => void;
  resetProcessing: () => void;
  loadBatchForReview: (batchName: string) => void;
  updateFieldRule: (fieldId: string, rule: FieldRule | null) => void;
  updateFieldAuthority: (fieldId: string, authority: AuthorityBinding | null) => void;  // Phase 11
  setCorrectorEnabled: (enabled: boolean) => void;
  setDescribePictures: (enabled: boolean) => void;
  setCorrectorCap: (cap: number) => void;
  acceptCorrectorProposal: (filename: string, field: string) => void;
  rejectCorrectorProposal: (filename: string, field: string) => void;
  cockpitSplitPercent: number;
  setCockpitSplitPercent: (v: number) => void;
}

const initialState = {
  step: 'upload' as WizardStep,
  view: 'wizard' as AppView,
  files: [],
  fields: [],
  sessionId: null,
  batchId: null,
  promptTemplate: null as string | null,
  selectedTemplateName: null as string | null,
  provider: 'openrouter' as OcrProvider,
  model: PROVIDER_DEFAULT_MODELS['openrouter'],
  correctorEnabled: false,
  correctorCap: 100,
  describePictures: false,
  processingState: initialProcessingState,
  results: [] as ResultRow[],
  cockpitSplitPercent: 50,
};

export const useWizardStore = create<WizardState>()(
  persist(
    (set) => ({
      ...initialState,
      setStep: (step) => set({ step }),
      setView: (view) => set({ view }),
      setSessionId: (sessionId) => set({ sessionId }),
      resetWizard: () =>
        set((state) => {
          state.files.forEach((f) => {
            if (f.preview) URL.revokeObjectURL(f.preview);
          });
          return initialState;
        }),
      updateFiles: (files) => set({ files }),
      setBatchId: (batchId) => set({ batchId }),
      setFields: (fields) => set({ fields }),
      setPromptTemplate: (promptTemplate) => set({ promptTemplate }),
      setSelectedTemplateName: (selectedTemplateName) => set({ selectedTemplateName }),
      setProvider: (provider) => set({ provider }),
      setModel: (model) => set({ model }),
      removeFile: (id) =>
        set((state) => {
          const target = state.files.find((f) => f.id === id);
          if (target?.preview) URL.revokeObjectURL(target.preview);
          return { files: state.files.filter((f) => f.id !== id) };
        }),
      clearFiles: () =>
        set((state) => {
          state.files.forEach((f) => {
            if (f.preview) URL.revokeObjectURL(f.preview);
          });
          return { files: [] };
        }),
      appendLiveFeedItem: (item) =>
        set((state) => ({
          processingState: {
            ...state.processingState,
            liveFeedItems: [...state.processingState.liveFeedItems, item],
          },
        })),
      setLastProgress: (p) =>
        set((state) => ({
          processingState: {
            ...state.processingState,
            lastProgress: p,
          },
        })),
      incrementConsecutiveFailures: () =>
        set((state) => ({
          processingState: {
            ...state.processingState,
            consecutiveFailures: state.processingState.consecutiveFailures + 1,
          },
        })),
      resetConsecutiveFailures: () =>
        set((state) => ({
          processingState: {
            ...state.processingState,
            consecutiveFailures: 0,
          },
        })),
      setCancelled: (cancelled) =>
        set((state) => ({
          processingState: {
            ...state.processingState,
            isCancelled: cancelled,
          },
        })),
      setIsProcessing: (processing) =>
        set((state) => ({
          processingState: {
            ...state.processingState,
            isProcessing: processing,
          },
        })),
      setResults: (rows) => set({ results: rows }),
      updateResultCell: (filename, field, value) =>
        set((state) => ({
          results: state.results.map((row) =>
            row.filename === filename
              ? {
                  ...row,
                  editedData: {
                    ...row.editedData,
                    [field]: value,
                  },
                }
              : row
          ),
        })),
      resetProcessing: () =>
        set({
          processingState: initialProcessingState,
          results: [],
        }),
      loadBatchForReview: (batchName) =>
        set({
          batchId: batchName,
          step: 'results',
          view: 'wizard',
        }),
      updateFieldRule: (fieldId, rule) =>
        set((state) => ({
          fields: state.fields.map((f) => (f.id === fieldId ? { ...f, rule } : f)),
        })),
      updateFieldAuthority: (fieldId, authority) =>
        set((state) => ({
          fields: state.fields.map((f) =>
            f.id === fieldId ? { ...f, authority } : f
          ),
        })),
      setCorrectorEnabled: (correctorEnabled) => set({ correctorEnabled }),
      setCorrectorCap: (correctorCap) => set({ correctorCap }),
      setDescribePictures: (describePictures) => set({ describePictures }),
      acceptCorrectorProposal: (filename, field) =>
        set((state) => ({
          results: state.results.map((r) => {
            if (r.filename !== filename) return r;
            const proposal = r.validation?.[field]?.corrector_proposal;
            const newEdited = { ...r.editedData };
            if (proposal != null) newEdited[field] = proposal;
            const newValidation = r.validation ? { ...r.validation } : null;
            if (newValidation && newValidation[field]) {
              newValidation[field] = { ...newValidation[field], status: 'valid' };
            }
            return { ...r, editedData: newEdited, validation: newValidation };
          }),
        })),
      rejectCorrectorProposal: (filename, field) =>
        set((state) => ({
          results: state.results.map((r) => {
            if (r.filename !== filename) return r;
            const newValidation = r.validation ? { ...r.validation } : null;
            if (newValidation && newValidation[field]) {
              newValidation[field] = { ...newValidation[field], status: 'invalid' };
            }
            return { ...r, validation: newValidation };
          }),
        })),
      setCockpitSplitPercent: (v) => set({ cockpitSplitPercent: v }),
    }),
    {
      name: 'wizard-storage',
      partialize: (state) => ({
        step: state.step,
        view: state.view,
        files: state.files.map(({ preview: _, ...rest }) => rest),
        fields: state.fields,
        sessionId: state.sessionId,
        batchId: state.batchId,
        promptTemplate: state.promptTemplate,
        selectedTemplateName: state.selectedTemplateName,
        provider: state.provider,
        model: state.model,
        correctorEnabled: state.correctorEnabled,
        correctorCap: state.correctorCap,
        describePictures: state.describePictures,
        cockpitSplitPercent: state.cockpitSplitPercent,
      }),
    }
  )
);
