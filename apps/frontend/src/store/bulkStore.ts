import { create } from 'zustand';
import { persist } from 'zustand/middleware';

// A separate store for the bulk workflow. wizardStore is deliberately left
// alone (beyond adding 'bulk' to its AppView union) so the interactive wizard
// keeps its exact behaviour and persisted shape.
//
// Only the run id and the step are persisted: everything else about a run lives
// on the backend, so a browser reload re-attaches to the same job rather than
// replaying stale client state.

export type BulkStep = 'start' | 'progress' | 'summary';

interface BulkState {
  step: BulkStep;
  runId: string | null;
  /** Folder names selected in the picker, in click order. */
  selectedFolders: string[];
  templateId: string | null;
  runName: string;
  provider: string;
  model: string;
  setStep: (step: BulkStep) => void;
  setRunId: (runId: string | null) => void;
  toggleFolder: (name: string) => void;
  setSelectedFolders: (names: string[]) => void;
  setTemplateId: (id: string | null) => void;
  setRunName: (name: string) => void;
  setProvider: (provider: string) => void;
  setModel: (model: string) => void;
  /** Return to a clean picker, e.g. after finishing or abandoning a run. */
  resetBulk: () => void;
}

const initialState = {
  step: 'start' as BulkStep,
  runId: null as string | null,
  selectedFolders: [] as string[],
  templateId: null as string | null,
  runName: '',
  provider: 'openrouter',
  model: '',
};

export const useBulkStore = create<BulkState>()(
  persist(
    (set) => ({
      ...initialState,
      setStep: (step) => set({ step }),
      setRunId: (runId) => set({ runId }),
      toggleFolder: (name) =>
        set((state) => ({
          selectedFolders: state.selectedFolders.includes(name)
            ? state.selectedFolders.filter((f) => f !== name)
            : [...state.selectedFolders, name],
        })),
      setSelectedFolders: (selectedFolders) => set({ selectedFolders }),
      setTemplateId: (templateId) => set({ templateId }),
      setRunName: (runName) => set({ runName }),
      setProvider: (provider) => set({ provider }),
      setModel: (model) => set({ model }),
      resetBulk: () => set(initialState),
    }),
    {
      name: 'bulk-storage',
      // The backend owns run state; persisting only the pointer to it is what
      // makes a reload re-attach instead of showing stale numbers.
      partialize: (state) => ({
        step: state.step,
        runId: state.runId,
        templateId: state.templateId,
        runName: state.runName,
        provider: state.provider,
        model: state.model,
      }),
    }
  )
);
