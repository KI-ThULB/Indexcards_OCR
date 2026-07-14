import React, { useState, useEffect } from 'react';
import { BookMarked } from 'lucide-react';

interface SaveTemplateDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onSave: (name: string) => void;
}

export const SaveTemplateDialog: React.FC<SaveTemplateDialogProps> = ({ isOpen, onClose, onSave }) => {
  const [name, setName] = useState('');

  // Reset name when dialog opens
  useEffect(() => {
    if (isOpen) {
      setName(''); // eslint-disable-line react-hooks/set-state-in-effect -- intentional reset on open
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const handleSave = () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    onSave(trimmed);
    onClose();
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleSave();
    } else if (e.key === 'Escape') {
      onClose();
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30"
      onClick={onClose}
    >
      <div
        className="bg-parchment-light border border-parchment-dark rounded-lg p-6 shadow-xl w-full max-w-sm mx-4 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3">
          <BookMarked className="w-5 h-5 text-archive-sepia" />
          <h3 className="text-lg font-serif text-archive-ink">Save as Template</h3>
        </div>

        <p className="text-sm text-archive-ink/60 italic font-light">
          Give this field configuration a name so you can reuse it in future batches.
        </p>

        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Template name (e.g., Music Archive)"
          className="w-full bg-parchment-light/30 border border-parchment-dark/50 rounded px-4 py-2 font-serif text-archive-ink focus:outline-none focus:border-archive-sepia/50 transition-colors"
          autoFocus
        />

        <div className="flex justify-end gap-2 pt-2">
          <button
            onClick={onClose}
            className="px-4 py-2 font-serif text-archive-ink/60 hover:text-archive-ink hover:bg-parchment-dark/10 rounded transition-all"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={!name.trim()}
            className={`
              px-4 py-2 font-serif rounded transition-all
              ${name.trim()
                ? 'bg-archive-sepia text-parchment-light hover:bg-archive-sepia/90 active:scale-95 shadow-md'
                : 'bg-parchment-dark/30 text-archive-ink/20 cursor-not-allowed'
              }
            `}
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
};
