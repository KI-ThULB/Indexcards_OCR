import React, { useState } from 'react';
import { LayoutGrid, Loader2, Trash2, ChevronDown } from 'lucide-react';
import { useTemplatesQuery, useDeleteTemplateMutation } from '../../api/templatesApi';
import type { Template } from '../../api/templatesApi';
import { useWizardStore } from '../../store/wizardStore';
import type { MetadataField } from '../../store/wizardStore';
import { toast } from 'sonner';

export const TemplateSelector: React.FC = () => {
  const { setFields, setPromptTemplate, selectedTemplateName, setSelectedTemplateName } = useWizardStore();
  const { data: templates, isLoading } = useTemplatesQuery();
  const deleteTemplateMutation = useDeleteTemplateMutation();
  const [isOpen, setIsOpen] = useState(false);
  const [selectedLabel, setSelectedLabel] = useState(selectedTemplateName ?? 'Custom / Blank Slate');

  const handleSelectBlank = () => {
    setFields([]);
    setPromptTemplate(null);
    setSelectedLabel('Custom / Blank Slate');
    setSelectedTemplateName(null);
    setIsOpen(false);
    toast.info('Cleared all extraction fields.');
  };

  const handleSelectTemplate = (template: Template) => {
    const newFields: MetadataField[] = template.fields.map((label) => ({
      id: Math.random().toString(36).substring(2, 11),
      label,
      type: 'text',
      rule: template.field_rules?.[label] ?? null,
    }));
    setFields(newFields);
    setPromptTemplate(template.prompt_template ?? null);
    setSelectedLabel(template.name);
    setSelectedTemplateName(template.name);
    setIsOpen(false);
    toast.success(`Applied template: ${template.name}`);
  };

  const handleDelete = (e: React.MouseEvent, id: string, name: string) => {
    e.stopPropagation();
    deleteTemplateMutation.mutate(id, {
      onSuccess: () => {
        if (selectedLabel === name) {
          setSelectedLabel('Custom / Blank Slate');
          setSelectedTemplateName(null);
        }
      },
    });
  };

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-archive-ink/40 text-sm italic py-2">
        <Loader2 className="w-4 h-4 animate-spin" />
        Fetching collection templates...
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <label className="text-xs uppercase tracking-widest text-archive-ink/40 font-semibold flex items-center gap-2">
        <LayoutGrid className="w-3 h-3" />
        Collection Type
      </label>

      <div className="relative">
        <button
          onClick={() => setIsOpen((prev) => !prev)}
          className="w-full flex items-center justify-between bg-parchment-light/30 border border-parchment-dark/50 rounded px-4 py-2 font-serif text-archive-ink focus:outline-none focus:border-archive-sepia/50 transition-colors hover:bg-parchment-dark/5 text-left"
        >
          <span className="truncate">{selectedLabel}</span>
          <ChevronDown className={`w-4 h-4 text-archive-ink/40 flex-shrink-0 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
        </button>

        {isOpen && (
          <>
            {/* Backdrop to close on outside click */}
            <div
              className="fixed inset-0 z-10"
              onClick={() => setIsOpen(false)}
            />
            <div className="absolute z-20 top-full left-0 right-0 mt-1 bg-parchment-light border border-parchment-dark/50 rounded shadow-lg overflow-hidden">
              {/* Blank Slate option */}
              <div
                onClick={handleSelectBlank}
                className="flex items-center justify-between px-4 py-2 hover:bg-parchment-dark/10 rounded cursor-pointer transition-colors"
              >
                <span className="font-serif text-archive-ink text-sm">Custom / Blank Slate</span>
              </div>

              {/* User-saved templates */}
              {templates && templates.length > 0 && (
                <div className="border-t border-parchment-dark/20">
                  {templates.map((t) => (
                    <div
                      key={t.id}
                      onClick={() => handleSelectTemplate(t)}
                      className="flex items-center justify-between px-4 py-2 hover:bg-parchment-dark/10 rounded cursor-pointer transition-colors group"
                    >
                      <span className="font-serif text-archive-ink text-sm truncate">{t.name}</span>
                      <button
                        onClick={(e) => handleDelete(e, t.id, t.name)}
                        className="p-1 text-archive-ink/30 hover:text-red-600 rounded transition-colors flex-shrink-0 ml-2"
                        title={`Delete template: ${t.name}`}
                        disabled={deleteTemplateMutation.isPending}
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  ))}
                </div>
              )}

              {templates && templates.length === 0 && (
                <div className="px-4 py-3 text-xs text-archive-ink/40 italic font-serif border-t border-parchment-dark/20">
                  No saved templates yet. Use "Save as Template" to create one.
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
};
