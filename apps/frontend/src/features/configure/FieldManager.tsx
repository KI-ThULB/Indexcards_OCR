import React, { useState } from 'react';
import { Plus, Trash2, Tag, Info, Save } from 'lucide-react';
import { useWizardStore } from '../../store/wizardStore';
import type { MetadataField } from '../../store/wizardStore';
import { toast } from 'sonner';
import { useCreateTemplateMutation } from '../../api/templatesApi';
import { SaveTemplateDialog } from './SaveTemplateDialog';
import { ValidationRuleEditor } from './ValidationRuleEditor';

export const FieldManager: React.FC = () => {
  const { fields, setFields, promptTemplate, correctorEnabled, updateFieldRule } = useWizardStore();
  const [newFieldLabel, setNewFieldLabel] = useState('');
  const [showSaveDialog, setShowSaveDialog] = useState(false);

  const createTemplateMutation = useCreateTemplateMutation();

  const addField = () => {
    if (!newFieldLabel.trim()) return;

    const newField: MetadataField = {
      id: Math.random().toString(36).substring(2, 11),
      label: newFieldLabel.trim(),
      type: 'text',
    };

    setFields([...fields, newField]);
    setNewFieldLabel('');
    toast.success(`Added field: ${newField.label}`);
  };

  const deleteField = (id: string, label: string) => {
    toast(`Remove field "${label}"?`, {
      action: {
        label: 'Confirm',
        onClick: () => {
          setFields(fields.filter((f) => f.id !== id));
          toast.success(`Removed ${label}.`);
        },
      },
      cancel: {
        label: 'Cancel',
        onClick: () => {},
      },
    });
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      addField();
    }
  };

  const handleSaveTemplate = (name: string) => {
    const fieldRules: Record<string, import('../../api/batchesApi').FieldRule> = {};
    fields.forEach((f) => {
      if (f.rule) fieldRules[f.label] = f.rule;
    });
    createTemplateMutation.mutate({
      name,
      fields: fields.map((f) => f.label),
      prompt_template: promptTemplate,
      field_rules: Object.keys(fieldRules).length > 0 ? fieldRules : null,
    });
    setShowSaveDialog(false);
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4">
        <h3 className="text-xl font-serif text-archive-ink">Field Definitions</h3>
        <p className="text-xs text-archive-ink/60 italic font-light">
          Define the specific pieces of information you want to extract from the index cards.
        </p>
      </div>

      <div className="flex gap-2">
        <div className="relative flex-1 group">
          <Tag className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-archive-ink/30 group-focus-within:text-archive-sepia/50 transition-colors" />
          <input
            type="text"
            value={newFieldLabel}
            onChange={(e) => setNewFieldLabel(e.target.value)}
            onKeyPress={handleKeyPress}
            placeholder="Field Label (e.g., Composer, Birth Date, etc.)"
            className="w-full pl-10 pr-4 py-3 bg-parchment-light/30 border border-parchment-dark/50 rounded font-serif text-archive-ink focus:outline-none focus:border-archive-sepia/50 transition-colors"
          />
        </div>
        <button
          onClick={addField}
          className="p-3 bg-archive-sepia text-parchment-light rounded hover:bg-archive-sepia/90 transition-all active:scale-95 shadow-md"
          title="Add extraction field"
        >
          <Plus className="w-6 h-6" />
        </button>
      </div>

      <div className="bg-parchment-light/30 border border-parchment-dark/50 rounded-lg overflow-hidden parchment-shadow min-h-[200px]">
        {fields.length === 0 ? (
          <div className="flex flex-col items-center justify-center p-12 text-archive-ink/30 italic">
            No fields defined. Select a template or add manually.
          </div>
        ) : (
          <div className="divide-y divide-parchment-dark/20 max-h-[400px] overflow-y-auto custom-scrollbar">
            {fields.map((field) => (
              <div key={field.id} className="flex flex-col border-b border-parchment-dark/20 last:border-0">
                <div className="flex items-center justify-between px-6 py-4 hover:bg-parchment-dark/5 transition-colors group">
                  <div className="flex items-center gap-3">
                    <div className="p-2 bg-parchment-dark/10 rounded border border-parchment-dark/20 group-hover:bg-archive-sepia/10 transition-colors">
                      <Tag className="w-4 h-4 text-archive-sepia/60" />
                    </div>
                    <span className="text-archive-ink font-serif text-lg">{field.label}</span>
                  </div>
                  <button
                    onClick={() => deleteField(field.id, field.label)}
                    className="p-2 text-archive-ink/30 hover:text-red-600 hover:bg-red-50 rounded-full transition-all group-hover:scale-110"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
                <ValidationRuleEditor
                  field={field}
                  correctorAvailable={correctorEnabled}
                  onChange={(rule) => updateFieldRule(field.id, rule)}
                />
              </div>
            ))}
          </div>
        )}
      </div>

      {fields.length > 0 && (
        <div className="flex items-center gap-2 p-4 bg-archive-sepia/5 border border-archive-sepia/20 rounded-lg text-archive-sepia/70 italic text-sm font-serif">
          <Info className="w-4 h-4 flex-shrink-0" />
          <span>The AI will look for these specific labels in the handwritten notes of your collection.</span>
        </div>
      )}

      <button
        onClick={() => setShowSaveDialog(true)}
        disabled={fields.length === 0}
        className={`
          flex items-center gap-2 px-4 py-2 rounded font-serif text-sm transition-all
          ${fields.length > 0
            ? 'border border-archive-sepia/30 text-archive-sepia hover:bg-archive-sepia/10 active:scale-95'
            : 'border border-parchment-dark/20 text-archive-ink/20 cursor-not-allowed'
          }
        `}
      >
        <Save className="w-4 h-4" />
        Save as Template
      </button>

      <SaveTemplateDialog
        isOpen={showSaveDialog}
        onClose={() => setShowSaveDialog(false)}
        onSave={handleSaveTemplate}
      />
    </div>
  );
};
