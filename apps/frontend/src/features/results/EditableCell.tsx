import React, { useState, useRef, useEffect } from 'react';

export interface EditableCellProps {
  value: string;
  onCommit: (value: string) => void;
  /** Optional: show edited indicator (dot + sepia color). Used by ResultsTable. */
  isEdited?: boolean;
}

export function EditableCell({ value, onCommit, isEdited = false }: EditableCellProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft]     = useState(value);
  const textareaRef           = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (editing && textareaRef.current) {
      textareaRef.current.focus();
      // Auto-resize on mount
      const ta = textareaRef.current;
      ta.style.height = 'auto';
      ta.style.height = ta.scrollHeight + 'px';
    }
  }, [editing]);

  // Keep draft in sync with external value changes (e.g. after retry)
  useEffect(() => {
    if (!editing) setDraft(value); // eslint-disable-line react-hooks/set-state-in-effect -- intentional sync from external value prop
  }, [value, editing]);

  const commit = () => {
    setEditing(false);
    const trimmed = draft.replace(/\n+$/, '');
    if (trimmed !== value) onCommit(trimmed);
  };

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setDraft(e.target.value);
    // Auto-resize on content change
    const ta = e.target;
    ta.style.height = 'auto';
    ta.style.height = ta.scrollHeight + 'px';
  };

  if (editing) {
    return (
      <textarea
        ref={textareaRef}
        value={draft}
        rows={1}
        onChange={handleChange}
        onBlur={commit}
        onKeyDown={(e) => {
          if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); commit(); }
          if (e.key === 'Escape') { setDraft(value); setEditing(false); }
        }}
        placeholder="Enter value..."
        className="w-full bg-transparent border-b border-archive-sepia/50 focus:outline-none font-serif text-sm text-archive-ink resize-none overflow-hidden"
      />
    );
  }

  return (
    <span
      onClick={() => { setDraft(value); setEditing(true); }}
      className={`cursor-text block w-full font-serif text-sm whitespace-pre-wrap ${isEdited ? 'text-archive-sepia font-semibold' : 'text-archive-ink/80'}`}
      title={isEdited ? 'Edited — click to change' : 'Click to edit'}
    >
      {value || <span className="text-archive-ink/30 italic">—</span>}
      {isEdited && <span className="ml-1 text-archive-sepia text-xs">•</span>}
    </span>
  );
}
