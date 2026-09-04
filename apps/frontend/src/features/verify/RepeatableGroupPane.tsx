import React, { useCallback, useMemo, useRef, useState } from 'react';
import { ChevronDown, ChevronUp, Layers, Plus, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { patchResult } from '../../api/batchesApi';
import type { AuditEntry, FieldGroup } from '../../api/batchesApi';
import { EditableCell } from '../results/EditableCell';
import { confidenceClasses, confidencePct } from '../results/confidence';
import {
  childConfidenceKey,
  childNames,
  effectiveItems,
} from '../results/groupValue';
import type { GroupItem } from '../results/groupValue';

interface RepeatableGroupPaneProps {
  label: string;
  group: FieldGroup;
  batchId: string;
  filename: string;
  data: Record<string, string>;
  editedData?: Record<string, string>;
  confidence?: Record<string, number> | null;
  /** Called after a successful change so the caller can refresh its results. */
  onChanged: () => void;
}

const auditEntry = (op: string, column: string, label: string): AuditEntry => ({
  id: `${op}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
  ts: new Date().toISOString(),
  op: op as AuditEntry['op'],
  column,
  label,
  affected: 1,
  scope: 'all',
  source: op as AuditEntry['source'],
});

/**
 * Curator editing of one repeatable group.
 *
 * Each entry is rendered as a small block of child values, so the repeating
 * title↔duration relationship stays visible. Value edits are debounced exactly
 * like scalar fields; structural changes (add, remove, reorder) apply
 * immediately and carry an audit entry, because they are not something a
 * curator does by accident.
 *
 * All four operations address the backend granularly (group + index + child),
 * which stores the whole edited array — so an insertion or removal can never
 * leave stale per-child data behind.
 */
export const RepeatableGroupPane: React.FC<RepeatableGroupPaneProps> = ({
  label,
  group,
  batchId,
  filename,
  data,
  editedData,
  confidence,
  onChanged,
}) => {
  const children = useMemo(() => childNames(group), [group]);
  const items: GroupItem[] = useMemo(
    () => effectiveItems(data, editedData, label),
    [data, editedData, label]
  );
  const [busy, setBusy] = useState(false);
  const timers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  const atLimit = items.length >= group.max_items;

  const commitValue = useCallback(
    (index: number, child: string, value: string) => {
      const key = `${index}.${child}`;
      clearTimeout(timers.current[key]);
      timers.current[key] = setTimeout(async () => {
        try {
          await patchResult(batchId, filename, {
            group: label, index, field: child, value,
            validation_status: 'verified',
          });
          onChanged();
        } catch {
          toast.error(`Änderung an „${child}" konnte nicht gespeichert werden.`);
        }
      }, 300);
    },
    [batchId, filename, label, onChanged]
  );

  const structural = useCallback(
    async (
      body: Parameters<typeof patchResult>[2],
      description: string,
      op: string
    ) => {
      setBusy(true);
      try {
        await patchResult(batchId, filename, {
          ...body,
          audit_entry: auditEntry(op, label, description),
        });
        onChanged();
      } catch (error) {
        const detail = (error as { response?: { data?: { detail?: string } } })
          .response?.data?.detail;
        toast.error(detail ?? `${description} fehlgeschlagen.`);
      } finally {
        setBusy(false);
      }
    },
    [batchId, filename, label, onChanged]
  );

  return (
    <section className="flex flex-col gap-2 py-3 border-b border-archive-100 last:border-0">
      <header className="flex items-center gap-2">
        <Layers className="w-3.5 h-3.5 text-archive-sepia shrink-0" />
        <span className="text-xs font-semibold text-archive-600 uppercase tracking-wide">
          {label}
        </span>
        <span className="text-[10px] text-archive-400 tabular-nums">
          {items.length} {items.length === 1 ? 'Eintrag' : 'Einträge'}
          {atLimit && ` · max. ${group.max_items}`}
        </span>
        <button
          onClick={() => structural({ group: label, group_op: 'add' },
                                    `Eintrag #${items.length + 1} hinzugefügt`, 'group-add')}
          disabled={busy || atLimit}
          title={atLimit ? `Maximal ${group.max_items} Einträge` : 'Eintrag hinzufügen'}
          className="ml-auto flex items-center gap-1 text-[11px] px-2 py-0.5 rounded border border-archive-200 text-archive-600 hover:bg-archive-50 disabled:opacity-30 disabled:cursor-not-allowed"
        >
          <Plus className="w-3 h-3" />
          Eintrag
        </button>
      </header>

      {items.length === 0 ? (
        <p className="text-xs text-archive-400 italic pl-5">
          Keine Einträge erkannt. Über „Eintrag" kann einer ergänzt werden.
        </p>
      ) : (
        <ol className="flex flex-col gap-2 pl-1">
          {items.map((item, index) => (
            <li
              key={index}
              className="rounded border border-archive-100 bg-archive-50/40 px-2 py-1.5"
            >
              <div className="flex items-center gap-1 mb-1">
                <span className="text-[11px] font-semibold text-archive-500 tabular-nums">
                  #{index + 1}
                </span>
                <button
                  onClick={() => structural(
                    { group: label, group_op: 'move', index, to_index: index - 1 },
                    `Eintrag #${index + 1} nach oben verschoben`, 'group-move')}
                  disabled={busy || index === 0}
                  title="Nach oben"
                  className="ml-auto p-0.5 text-archive-400 hover:text-archive-700 disabled:opacity-20 disabled:cursor-not-allowed"
                >
                  <ChevronUp className="w-3.5 h-3.5" />
                </button>
                <button
                  onClick={() => structural(
                    { group: label, group_op: 'move', index, to_index: index + 1 },
                    `Eintrag #${index + 1} nach unten verschoben`, 'group-move')}
                  disabled={busy || index === items.length - 1}
                  title="Nach unten"
                  className="p-0.5 text-archive-400 hover:text-archive-700 disabled:opacity-20 disabled:cursor-not-allowed"
                >
                  <ChevronDown className="w-3.5 h-3.5" />
                </button>
                <button
                  onClick={() => structural(
                    { group: label, group_op: 'remove', index },
                    `Eintrag #${index + 1} entfernt`, 'group-remove')}
                  disabled={busy}
                  title="Eintrag entfernen"
                  className="p-0.5 text-archive-400 hover:text-red-700 disabled:opacity-20"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>

              {children.map((child) => {
                const score = confidence?.[childConfidenceKey(label, index, child)];
                return (
                  <div key={child} className="flex items-baseline gap-2">
                    <span className="text-[11px] text-archive-500 min-w-[86px] shrink-0">
                      {child}
                    </span>
                    <div className="flex-1 min-w-0">
                      <EditableCell
                        value={item[child] ?? ''}
                        onCommit={(value) => commitValue(index, child, value)}
                      />
                    </div>
                    {score !== undefined && score !== null && (
                      <span
                        className={`shrink-0 rounded px-1 text-[10px] font-mono leading-5 ${confidenceClasses(score)}`}
                        title={`VLM-Konfidenz für „${label}[${index}].${child}"`}
                      >
                        {confidencePct(score)}
                      </span>
                    )}
                  </div>
                );
              })}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
};
