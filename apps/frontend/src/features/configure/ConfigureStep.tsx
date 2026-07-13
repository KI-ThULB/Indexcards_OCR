import React, { useState } from 'react';
import { Play, Archive, Info } from 'lucide-react';
import { useWizardStore } from '../../store/wizardStore';
import { TemplateSelector } from './TemplateSelector';
import { ProviderSelector } from './ProviderSelector';
import { FieldManager } from './FieldManager';
import { PromptTemplateEditor } from './PromptTemplateEditor';
import { ImagePreview } from './ImagePreview';
import { useCreateBatchMutation, useStartBatchMutation } from '../../api/batchesApi';
import type { FieldRule, AuthorityBinding } from '../../api/batchesApi';
import { toast } from 'sonner';
import { WizardNav } from '../../components/WizardNav';

export const ConfigureStep: React.FC = () => {
  const {
    files, fields, sessionId, batchId, provider, model, setStep, setBatchId, promptTemplate,
    correctorEnabled, correctorCap, setCorrectorEnabled, setCorrectorCap,
    describePictures, setDescribePictures,
  } = useWizardStore();
  const [batchName, setBatchName] = useState(`Batch_${new Date().toISOString().slice(0, 16).replace('T', '_').replaceAll(':', '-')}`);

  const createBatchMutation = useCreateBatchMutation();
  const startBatchMutation = useStartBatchMutation();

  const handleBack = () => {
    setStep('upload');
  };

  const handleStartExtraction = () => {
    if (!sessionId || files.length === 0) {
      toast.error('No session or files found. Please restart.');
      setStep('upload');
      return;
    }

    if (fields.length === 0) {
      toast.error('Please define at least one field for extraction.');
      return;
    }

    if (!batchName.trim()) {
      toast.error('Please provide a batch name.');
      return;
    }

    // Prepare labels for the backend
    const fieldLabels = fields.map((f) => f.label);

    // Build field_rules map keyed by field label
    const fieldRules: Record<string, FieldRule> = {};
    fields.forEach((f) => {
      if (f.rule) fieldRules[f.label] = f.rule;
    });

    // Build authority_bindings map keyed by field label — Phase 11
    const authorityBindings: Record<string, AuthorityBinding> = {};
    fields.forEach((f) => {
      if (f.authority?.type) authorityBindings[f.label] = f.authority;
    });

    createBatchMutation.mutate(
      {
        custom_name: batchName.trim(),
        session_id: sessionId,
        fields: fieldLabels,
        prompt_template: promptTemplate,
        field_rules: Object.keys(fieldRules).length > 0 ? fieldRules : null,
        corrector_enabled: correctorEnabled,
        corrector_cap: correctorCap,
        authority_bindings: Object.keys(authorityBindings).length > 0 ? authorityBindings : null,
        describe_pictures: describePictures,
      },
      {
        onSuccess: (data) => {
          setBatchId(data.batch_name);
          // Start batch with the selected provider and model
          startBatchMutation.mutate({ batchName: data.batch_name, provider, model }, {
            onSuccess: () => {
              setStep('processing');
            },
          });
        },
      }
    );
  };

  const isPending = createBatchMutation.isPending || startBatchMutation.isPending;

  return (
    <div className="flex-1 max-w-6xl mx-auto w-full space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-700">
      <div className="flex flex-col gap-2">
        <h2 className="text-3xl font-serif text-archive-sepia">Configure Archival Batch</h2>
        <p className="text-archive-ink/60 italic font-light">
          Define how the Archive should interpret and extract information from your staged items.
        </p>
      </div>

      {/* Image preview - standalone above the grid */}
      {files.length > 0 && (
        <div className="bg-parchment-light/30 border border-parchment-dark/50 p-4 rounded-lg parchment-shadow">
          <ImagePreview />
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* Card 1 — What to extract */}
        <div className="space-y-6 bg-parchment-light/30 border border-parchment-dark/50 p-6 rounded-lg parchment-shadow">
          <div className="flex flex-col gap-2">
            <label className="text-xs uppercase tracking-widest text-archive-ink/40 font-semibold flex items-center gap-2">
              <Archive className="w-3 h-3" />
              Batch Identity
            </label>
            <input
              type="text"
              value={batchName}
              onChange={(e) => setBatchName(e.target.value)}
              placeholder="Unique Batch Name"
              className="w-full bg-parchment-light/30 border border-parchment-dark/50 rounded px-4 py-2 font-serif text-archive-ink focus:outline-none focus:border-archive-sepia/50 transition-colors"
            />
          </div>

          <TemplateSelector />

          <div className="pt-4 border-t border-parchment-dark/30">
            <FieldManager />
          </div>

          <div className="pt-4 border-t border-parchment-dark/30 space-y-2">
            <h4 className="text-xs uppercase tracking-widest text-archive-ink/40 font-semibold">Batch Summary</h4>
            <div className="flex flex-col gap-1 text-sm text-archive-ink/70 font-serif italic">
              <span>• {files.length} Collection Items</span>
              <span>• {fields.length} Metadata Fields</span>
            </div>
          </div>
        </div>

        {/* Card 2 — How to extract */}
        <div className="space-y-6 bg-parchment-light/30 border border-parchment-dark/50 p-6 rounded-lg parchment-shadow">
          <ProviderSelector />

          <div className="pt-4 border-t border-parchment-dark/30">
            <PromptTemplateEditor />
          </div>

          <div className="border-t border-parchment-dark/30 pt-4 mt-4 space-y-2">
            <label className="flex items-center gap-2 text-sm font-mono text-archive-ink/70 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={correctorEnabled}
                onChange={(e) => setCorrectorEnabled(e.target.checked)}
                className="accent-archive-sepia"
              />
              Enable LLM correction for invalid fields
            </label>
            {correctorEnabled && (
              <label className="flex items-center gap-2 text-sm mt-2 ml-6 text-archive-ink/60">
                Max correction calls per batch:
                <input
                  type="number"
                  min={1}
                  max={10000}
                  value={correctorCap}
                  onChange={(e) => setCorrectorCap(Number(e.target.value) || 100)}
                  className="w-24 bg-parchment-light/30 border border-parchment-dark/50 rounded px-2 py-1 font-mono text-xs text-archive-ink focus:outline-none focus:border-archive-sepia/50 transition-colors"
                />
              </label>
            )}
          </div>

          <div className="border-t border-parchment-dark/30 pt-4 mt-4 space-y-1">
            <label className="flex items-center gap-2 text-sm font-mono text-archive-ink/70 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={describePictures}
                onChange={(e) => setDescribePictures(e.target.checked)}
                className="accent-archive-sepia"
              />
              Bilder auf den Karten beschreiben
            </label>
            <p className="text-xs text-archive-ink/50 ml-6">
              Erkennt Bilder/Zeichnungen/Fotos auf einer Karte und ergänzt eine Beschreibung
              im Feld „Bildbeschreibung“.
            </p>
          </div>
        </div>
      </div>

      <div className="flex items-center gap-2 p-4 bg-archive-ink/5 border border-archive-ink/20 rounded-lg text-archive-ink/60 text-xs italic">
        <Info className="w-4 h-4 flex-shrink-0" />
        <span>Changes to the batch name or templates will not affect your staged files.</span>
      </div>

      {batchId && (
        <div className="flex items-center gap-2 p-4 bg-archive-sepia/5 border border-archive-sepia/20 rounded-lg text-archive-ink/60 text-sm italic font-serif">
          <Info className="w-4 h-4 flex-shrink-0 text-archive-sepia/60" />
          <span>A batch has already been created for this session. Use <strong>"Start New Batch"</strong> from the Results step to begin fresh.</span>
        </div>
      )}

      <WizardNav
        back={{
          label: 'Return to Staging',
          onClick: handleBack,
          disabled: isPending,
        }}
        next={{
          label: 'Commence Processing',
          onClick: handleStartExtraction,
          disabled: fields.length === 0 || isPending || !batchName.trim() || batchId !== null,
          loading: isPending,
          icon: <Play className="w-5 h-5 fill-current" />,
        }}
      />
    </div>
  );
};
