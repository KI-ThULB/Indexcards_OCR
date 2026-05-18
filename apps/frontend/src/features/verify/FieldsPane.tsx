import { useState, useRef, useCallback, useMemo } from 'react';
import axios from 'axios';
import { EditableCell } from '../results/EditableCell';
import { CockpitBadge } from './CockpitBadge';
import { useWizardStore } from '../../store/wizardStore';
import type { ResultRow } from '../../store/wizardStore';

interface FieldsPaneProps {
  card: ResultRow;
  batchId: string;
  onFieldVerified?: (field: string) => void;
}

export function FieldsPane({ card, batchId, onFieldVerified }: FieldsPaneProps) {
  const { updateResultCell } = useWizardStore();

  // Multi-entry detection: _entries key holds a JSON array of per-entry data dicts
  const hasEntries = Boolean(card.data['_entries']);
  const entries: Record<string, string>[] = useMemo(() => {
    if (!hasEntries) return [card.data];
    try {
      return JSON.parse(card.data['_entries'] as string) as Record<string, string>[];
    } catch {
      return [card.data];
    }
  }, [hasEntries, card.data]);

  const [activeEntryIndex, setActiveEntryIndex] = useState(0);
  const activeEntry = entries[activeEntryIndex] ?? {};

  // Virtual filename for multi-entry rows — matches the existing key pattern from ResultsTable.tsx
  const effectiveFilename = hasEntries
    ? `${card.filename}__entry_${activeEntryIndex}`
    : card.filename;

  // Derive visible fields: exclude internal _-prefixed keys
  const visibleFields = useMemo(
    () => Object.keys(activeEntry).filter((k) => !k.startsWith('_')),
    [activeEntry]
  );

  // Debounce timers per field for PATCH calls
  const patchTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  const handleCommit = useCallback(
    (field: string, newVal: string) => {
      // 1. Update Zustand editedData for the (possibly virtual) filename
      updateResultCell(effectiveFilename, field, newVal);

      // 2. Flip validation status to 'verified' in Zustand for the base card filename
      useWizardStore.setState((state) => ({
        results: state.results.map((r) => {
          if (r.filename !== card.filename) return r;
          const newValidation = r.validation ? { ...r.validation } : {};
          newValidation[field] = {
            ...(newValidation[field] ?? { status: 'valid' }),
            status: 'verified',
          };
          return { ...r, validation: newValidation };
        }),
      }));

      // 3. Debounced PATCH to backend (300ms window; coalesces rapid edits)
      clearTimeout(patchTimers.current[field]);
      patchTimers.current[field] = setTimeout(async () => {
        try {
          await axios.patch(
            `/api/v1/batches/${batchId}/results/${encodeURIComponent(card.filename)}`,
            { field, value: newVal, validation_status: 'verified' }
          );
        } catch (err) {
          // Non-blocking: Zustand already has the edit; PATCH failure is non-fatal for UX
          console.warn('[VerifyStep] PATCH failed for', field, err);
        }
      }, 300);

      onFieldVerified?.(field);
    },
    [card, effectiveFilename, batchId, updateResultCell, onFieldVerified]
  );

  // Progress indicator: count fields with verified status
  const verifiedCount = useMemo(() => {
    if (!card.validation) return 0;
    return Object.values(card.validation).filter((v) => v.status === 'verified').length;
  }, [card.validation]);

  const totalFields = visibleFields.length;

  return (
    <div className="flex flex-col h-full">
      {/* Pane header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-archive-100">
        <h3 className="text-sm font-semibold text-archive-700 font-serif truncate" title={card.filename}>
          {card.filename}
        </h3>
        <span className="text-xs text-archive-500 shrink-0 ml-2">
          {verifiedCount}/{totalFields} fields verified
        </span>
      </div>

      {/* Multi-entry tabs — shown only when card has multiple entries */}
      {hasEntries && (
        <div className="flex gap-1 border-b border-archive-200 px-4 pt-2">
          {entries.map((_, idx) => (
            <button
              key={idx}
              onClick={() => setActiveEntryIndex(idx)}
              className={`px-3 py-1 text-sm rounded-t-md transition-colors ${
                idx === activeEntryIndex
                  ? 'bg-parchment-paper border border-b-0 border-archive-300 text-archive-800 font-medium'
                  : 'text-archive-500 hover:text-archive-700'
              }`}
            >
              Entry {idx + 1}
            </button>
          ))}
        </div>
      )}

      {/* Scrollable field list */}
      <div className="overflow-y-auto flex-1 px-4 py-2">
        {visibleFields.length === 0 ? (
          <p className="text-xs text-archive-400 italic mt-4">No fields available.</p>
        ) : (
          visibleFields.map((field) => (
            <div
              key={field}
              className="flex flex-col gap-0.5 py-2 border-b border-archive-100 last:border-0"
            >
              {/* Field label + validation badge */}
              <div className="flex items-center gap-2">
                <span className="text-xs font-semibold text-archive-600 uppercase tracking-wide min-w-[120px]">
                  {field}
                </span>
                <CockpitBadge
                  outcome={card.validation?.[field]}
                  filename={effectiveFilename}
                  field={field}
                />
              </div>

              {/* Inline editable cell */}
              <EditableCell
                value={card.editedData?.[field] ?? (activeEntry[field] ?? '')}
                onCommit={(newVal) => handleCommit(field, newVal)}
                isEdited={Boolean(card.editedData?.[field] !== undefined)}
              />
            </div>
          ))
        )}
      </div>
    </div>
  );
}
