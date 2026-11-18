import { toast } from 'sonner';
import { useState, useCallback, useMemo } from 'react';
import { useSyncedResultPatch } from '../../api/batchesApi';
import { EditableCell } from '../results/EditableCell';
import { CockpitBadge } from './CockpitBadge';
import { useWizardStore } from '../../store/wizardStore';
import type { ResultRow } from '../../store/wizardStore';
import { confidenceClasses, confidencePct } from '../results/confidence';
import { useBatchConfigQuery } from '../../api/batchesApi';
import { isGroupField } from '../results/groupValue';
import { RepeatableGroupPane } from './RepeatableGroupPane';

interface FieldsPaneProps {
  card: ResultRow;
  batchId: string;
  onFieldVerified?: (field: string) => void;
  /** Called after a repeatable-group change so the caller can reload results. */
  onGroupChanged?: () => void;
}

export function FieldsPane({ card, batchId, onFieldVerified, onGroupChanged }: FieldsPaneProps) {
  const { updateResultCell } = useWizardStore();
  // Group definitions come from the batch's own frozen config, so a card is
  // always rendered against the schema it was extracted with.
  const { data: batchConfig } = useBatchConfigQuery(batchId);
  const fieldGroups = batchConfig?.field_groups ?? null;

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

  const patchResult = useSyncedResultPatch();

  const handleCommit = useCallback(
    async (field: string, newVal: string) => {
      // Check if value is actually changing (needed for reconciliation-clearing logic)
      const oldVal = card.editedData?.[field] ?? (activeEntry[field] ?? '');
      const valueChanging = newVal !== oldVal;

      // Check if this field has an existing reconciliation outcome
      const hasReconciliation = !!card.validation?.[field]?.reconciliation;

      // 1. Update Zustand editedData for the (possibly virtual) filename
      updateResultCell(effectiveFilename, field, newVal);

      // 2. Flip validation status to 'verified' in Zustand for the base card filename.
      //    Per 11-01 convention: also clear reconciliation when value changes on a reconciled cell.
      useWizardStore.setState((state) => ({
        results: state.results.map((r) => {
          if (r.filename !== card.filename) return r;
          const newValidation = r.validation ? { ...r.validation } : {};
          newValidation[field] = {
            ...(newValidation[field] ?? { status: 'valid' }),
            status: 'verified',
            // RECONCILIATION-CLEARING-ON-EDIT: clear reconciliation when value changes
            ...(hasReconciliation && valueChanging ? { reconciliation: null } : {}),
          };
          return { ...r, validation: newValidation };
        }),
      }));

      const { batchRevision } = useWizardStore.getState();
      try {
        if (!batchId) return;
        const saved = await patchResult(batchId, card.filename, {
          field,
          value: newVal,
          validation_status: 'verified',
        });
        useWizardStore.setState(state => {
          if (state.batchRevision !== batchRevision) return state;
          return {
            results: state.results.map(row => {
              if (row.filename !== card.filename || row.editedData[field] !== newVal) return row;
              return { ...row, validation: { ...row.validation, [field]: saved.validation?.[field] ?? null } };
            }),
          };
        });
        onFieldVerified?.(field);
      } catch (err) {
        toast.error('Could not save field edit. Reload to see the saved value.');
        console.warn('[VerifyStep] PATCH failed for', field, err);
      }
    },
    [card, activeEntry, effectiveFilename, batchId, updateResultCell, onFieldVerified, patchResult]
  );

  // Progress indicator: count fields with verified status
  const verifiedCount = useMemo(() => {
    if (!card.validation) return 0;
    return Object.values(card.validation).filter((v) => v?.status === 'verified').length;
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
            isGroupField(field, fieldGroups) ? (
              <RepeatableGroupPane
                key={field}
                label={field}
                group={fieldGroups![field]}
                batchId={batchId}
                filename={card.filename}
                data={card.data}
                editedData={card.editedData}
                confidence={card.confidence}
                onChanged={() => onGroupChanged?.()}
              />
            ) : (
            <div
              key={field}
              className="flex flex-col gap-0.5 py-2 border-b border-archive-100 last:border-0"
            >
              {/* Field label + validation badge + VLM confidence */}
              <div className="flex items-center gap-2">
                <span className="text-xs font-semibold text-archive-600 uppercase tracking-wide min-w-[120px]">
                  {field}
                </span>
                <CockpitBadge
                  outcome={card.validation?.[field]}
                  filename={effectiveFilename}
                  field={field}
                />
                {!hasEntries && card.confidence?.[field] !== undefined && card.confidence?.[field] !== null && (
                  <span
                    className={`shrink-0 rounded px-1 text-[10px] font-mono leading-5 ${confidenceClasses(card.confidence[field])}`}
                    title={`VLM-Konfidenz für „${field}“`}
                  >
                    {confidencePct(card.confidence[field])}
                  </span>
                )}
              </div>

              {/* Inline editable cell */}
              <EditableCell
                value={card.editedData?.[field] ?? (activeEntry[field] ?? '')}
                onCommit={(newVal) => handleCommit(field, newVal)}
                isEdited={Boolean(card.editedData?.[field] !== undefined)}
              />
            </div>
            )
          ))
        )}
      </div>
    </div>
  );
}
