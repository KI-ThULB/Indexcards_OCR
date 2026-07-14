import React, { useState, useEffect, useRef } from 'react';
import { ChevronDown } from 'lucide-react';
import { useWizardStore } from '../../store/wizardStore';

const DEFAULT_TEMPLATE = `Du bist ein Experte für die Digitalisierung historischer Archivkarteikarten.

Deine Aufgabe ist es, die Informationen von der Karteikarte präzise zu extrahieren.
Achte besonders auf die Handschrift und mögliche Streichungen.

**Extrahiere folgende Felder:**
{{fields}}

Falls ein Feld nicht auf der Karte vorhanden ist oder nicht entziffert werden kann, verwende einen leeren String ("").
Ändere nichts an der Schreibweise historischer Begriffe, außer bei offensichtlichen Tippfehlern.

**AUSGABEFORMAT:** Antworte NUR mit einem validen JSON-Objekt.`;

export const PromptTemplateEditor: React.FC = () => {
  const { fields, promptTemplate, setPromptTemplate } = useWizardStore();
  const [isExpanded, setIsExpanded] = useState(false);
  const [isPreview, setIsPreview] = useState(false);

  // Local state for instant textarea feedback; debounced write to Zustand
  const effectiveTemplate = promptTemplate ?? DEFAULT_TEMPLATE;
  const [localTemplate, setLocalTemplate] = useState(effectiveTemplate);
  const isLocalEdit = useRef(false);
  const isUserTyping = useRef(false);

  // Sync store → local when store changes externally (e.g., template load)
  useEffect(() => {
    if (!isLocalEdit.current) {
      setLocalTemplate(promptTemplate ?? DEFAULT_TEMPLATE); // eslint-disable-line react-hooks/set-state-in-effect -- intentional sync from external store prop
    }
    isLocalEdit.current = false;
  }, [promptTemplate]);

  // Debounced local → store write (300ms) — only for user edits
  useEffect(() => {
    if (!isUserTyping.current) return;
    const timeout = setTimeout(() => {
      isUserTyping.current = false;
      const storeValue = localTemplate === DEFAULT_TEMPLATE ? null : localTemplate || null;
      if (storeValue !== promptTemplate) {
        isLocalEdit.current = true;
        setPromptTemplate(storeValue);
      }
    }, 300);
    return () => clearTimeout(timeout);
  }, [localTemplate, promptTemplate, setPromptTemplate]);

  const fieldsBlock = fields
    .map((f, i) => `${i + 1}. **${f.label}**: Extrahiere den Wert fur das Feld '${f.label}'.`)
    .join('\n');

  const preview = localTemplate.includes('{{fields}}')
    ? localTemplate.replace('{{fields}}', fieldsBlock)
    : localTemplate + '\n\n' + fieldsBlock;

  return (
    <div className="border border-parchment-dark/50 rounded-lg overflow-hidden bg-parchment-light/20">
      {/* Header row */}
      <button
        onClick={() => setIsExpanded((prev) => !prev)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-parchment-dark/5 transition-colors focus:outline-none"
      >
        <span className="font-serif text-archive-ink text-base">Prompt Template</span>
        <ChevronDown
          className={`w-4 h-4 text-archive-ink/40 transition-transform duration-200 ${isExpanded ? 'rotate-180' : ''}`}
        />
      </button>

      {isExpanded && (
        <div className="px-4 pb-4 space-y-3 border-t border-parchment-dark/20">
          {/* Hint */}
          <p className="text-xs text-archive-ink/60 italic pt-3">
            Use <code className="font-mono bg-parchment-dark/10 px-1 rounded">{'{{fields}}'}</code> as the placeholder where the field list will appear. Leave blank to use the default template.
          </p>

          {/* Edit / Preview toggle */}
          <div className="flex items-center gap-3">
            <button
              onClick={() => setIsPreview(false)}
              className={`text-sm underline transition-colors ${!isPreview ? 'text-archive-sepia' : 'text-archive-ink/40 hover:text-archive-ink'}`}
            >
              Edit
            </button>
            <span className="text-archive-ink/20">|</span>
            <button
              onClick={() => setIsPreview(true)}
              className={`text-sm underline transition-colors ${isPreview ? 'text-archive-sepia' : 'text-archive-ink/40 hover:text-archive-ink'}`}
            >
              Preview
            </button>
          </div>

          {/* Edit mode */}
          {!isPreview && (
            <textarea
              className="w-full h-48 font-mono text-sm bg-parchment-light/30 border border-parchment-dark/50 rounded p-3 focus:outline-none focus:border-archive-sepia/50 resize-y"
              value={localTemplate}
              onChange={(e) => { isUserTyping.current = true; setLocalTemplate(e.target.value); }}
            />
          )}

          {/* Preview mode */}
          {isPreview && (
            <pre className="text-xs font-mono bg-parchment-dark/5 border border-parchment-dark/30 rounded p-4 whitespace-pre-wrap max-h-64 overflow-y-auto">
              {preview}
            </pre>
          )}

          {/* Reset to default — only visible when promptTemplate is not null */}
          {promptTemplate !== null && (
            <button
              onClick={() => {
                setLocalTemplate(DEFAULT_TEMPLATE);
                setPromptTemplate(null);
              }}
              className="text-xs text-archive-ink/50 hover:text-archive-ink underline transition-colors"
            >
              Reset to default
            </button>
          )}
        </div>
      )}
    </div>
  );
};
