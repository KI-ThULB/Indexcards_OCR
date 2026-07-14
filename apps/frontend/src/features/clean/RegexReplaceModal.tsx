import React, { useState } from 'react';

interface RegexReplaceModalProps {
  isOpen: boolean;
  onClose: () => void;
  onApply: (findPattern: string, replaceWith: string) => void;
}

/**
 * Modal for Regex Replace transform.
 * Inputs: find (regex) + replace (string with capture group support using $1, $2 syntax).
 * Validates the find pattern via try/catch on every keystroke.
 * Apply is disabled when findPattern is empty or invalid.
 */
export function RegexReplaceModal({ isOpen, onClose, onApply }: RegexReplaceModalProps) {
  const [findPattern, setFindPattern] = useState('');
  const [replaceWith, setReplaceWith] = useState('');
  const [regexError, setRegexError] = useState(false);

  if (!isOpen) return null;

  const handleFindChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    setFindPattern(val);
    if (!val) {
      setRegexError(false);
      return;
    }
    try {
      new RegExp(val, 'gu');
      setRegexError(false);
    } catch {
      setRegexError(true);
    }
  };

  const handleApply = () => {
    if (!findPattern || regexError) return;
    onApply(findPattern, replaceWith);
    onClose();
    // Reset state for next use
    setFindPattern('');
    setReplaceWith('');
    setRegexError(false);
  };

  const handleClose = () => {
    onClose();
    setFindPattern('');
    setReplaceWith('');
    setRegexError(false);
  };

  return (
    <div className="fixed inset-0 bg-black/30 z-50 flex items-center justify-center">
      <div className="bg-parchment-paper rounded-lg shadow-xl w-96 p-5 flex flex-col gap-4">
        <h3 className="text-sm font-semibold text-archive-800">Regex Replace</h3>

        {/* Find input */}
        <div className="flex flex-col gap-1">
          <label className="text-xs text-archive-600">Find (regex)</label>
          <input
            type="text"
            value={findPattern}
            onChange={handleFindChange}
            placeholder="e.g. (\w+)\s+(\w+)"
            className={`border rounded px-2 py-1.5 text-sm font-mono ${
              regexError ? 'border-red-400 bg-red-50' : 'border-archive-300'
            }`}
            autoFocus
          />
          {regexError && (
            <span className="text-xs text-red-600">Invalid regex</span>
          )}
        </div>

        {/* Replace input */}
        <div className="flex flex-col gap-1">
          <label className="text-xs text-archive-600">Replace with</label>
          <input
            type="text"
            value={replaceWith}
            onChange={(e) => setReplaceWith(e.target.value)}
            placeholder="e.g. $2 $1  (use $1, $2 for capture groups)"
            className="border border-archive-300 rounded px-2 py-1.5 text-sm font-mono"
          />
        </div>

        {/* Actions */}
        <div className="flex justify-end gap-2 mt-2">
          <button
            onClick={handleClose}
            className="px-3 py-1.5 text-sm border border-archive-300 rounded text-archive-700 hover:bg-archive-50"
          >
            Cancel
          </button>
          <button
            onClick={handleApply}
            disabled={!findPattern || regexError}
            className="px-3 py-1.5 text-sm bg-archive-700 text-parchment-paper rounded hover:bg-archive-900 disabled:opacity-40"
          >
            Apply to column
          </button>
        </div>
      </div>
    </div>
  );
}
