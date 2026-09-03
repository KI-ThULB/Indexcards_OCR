import React, { useState } from 'react';
import { ChevronDown, ChevronUp, Layers, Plus, Trash2 } from 'lucide-react';
import { useWizardStore } from '../../store/wizardStore';
import type { MetadataField } from '../../store/wizardStore';

interface RepeatableGroupEditorProps {
  field: MetadataField;
}

/**
 * Editor for one repeatable group: its instruction, its child fields, and their
 * order. Rendered inline under the group's row in FieldManager, indented so the
 * parent/child relationship is visible at a glance.
 *
 * The group label itself stays an ordinary entry in the template's field list —
 * only the structure lives here.
 */
export const RepeatableGroupEditor: React.FC<RepeatableGroupEditorProps> = ({ field }) => {
  const {
    updateGroupDescription,
    addGroupChild,
    updateGroupChild,
    moveGroupChild,
    removeGroupChild,
  } = useWizardStore();
  const [newChild, setNewChild] = useState('');

  const group = field.group;
  if (!group) return null;

  const handleAddChild = () => {
    const name = newChild.trim();
    if (!name) return;
    if (group.fields.some((c) => c.name === name)) return;
    addGroupChild(field.id, name);
    setNewChild('');
  };

  return (
    <div className="pl-14 pr-6 pb-4 space-y-3 bg-parchment-dark/5">
      {/* Group instruction passed to the model */}
      <div className="flex flex-col gap-1">
        <label className="text-[10px] uppercase tracking-widest text-archive-ink/40 font-semibold">
          Anweisung für die Gruppe
        </label>
        <input
          type="text"
          value={group.description ?? ''}
          onChange={(e) => updateGroupDescription(field.id, e.target.value)}
          placeholder="z. B. Die Einzeltitel des Tonbands, je Zeile mit zugehöriger Spieldauer."
          className="w-full bg-parchment-light/40 border border-parchment-dark/50 rounded px-3 py-2 text-sm text-archive-ink focus:outline-none focus:border-archive-sepia/50"
        />
      </div>

      {/* Child fields */}
      <div className="flex flex-col gap-1">
        <label className="text-[10px] uppercase tracking-widest text-archive-ink/40 font-semibold">
          Felder je Eintrag ({group.fields.length})
        </label>

        {group.fields.length === 0 ? (
          <p className="text-xs text-archive-ink/40 italic py-1">
            Noch keine Felder. Eine Gruppe ohne Felder wird nicht extrahiert.
          </p>
        ) : (
          <ul className="flex flex-col divide-y divide-parchment-dark/20 border border-parchment-dark/30 rounded overflow-hidden">
            {group.fields.map((child, index) => (
              <li
                key={`${child.name}-${index}`}
                className="flex items-center gap-2 px-3 py-2 bg-parchment-light/30"
              >
                <span className="text-archive-ink/30 font-mono text-xs w-4 shrink-0">
                  {index === group.fields.length - 1 ? '└' : '├'}
                </span>
                <input
                  type="text"
                  value={child.name}
                  onChange={(e) => updateGroupChild(field.id, index, { name: e.target.value })}
                  className="w-40 shrink-0 bg-transparent border-b border-parchment-dark/40 px-1 py-0.5 text-sm font-serif text-archive-ink focus:outline-none focus:border-archive-sepia"
                  aria-label={`Name des Feldes ${index + 1}`}
                />
                <input
                  type="text"
                  value={child.description ?? ''}
                  onChange={(e) =>
                    updateGroupChild(field.id, index, { description: e.target.value || null })
                  }
                  placeholder="Beschreibung (optional, wird dem Modell mitgegeben)"
                  className="flex-1 bg-transparent border-b border-parchment-dark/20 px-1 py-0.5 text-xs text-archive-ink/70 focus:outline-none focus:border-archive-sepia/50"
                  aria-label={`Beschreibung des Feldes ${index + 1}`}
                />
                <button
                  onClick={() => moveGroupChild(field.id, index, -1)}
                  disabled={index === 0}
                  title="Nach oben"
                  className="p-1 text-archive-ink/40 hover:text-archive-ink disabled:opacity-20 disabled:cursor-not-allowed"
                >
                  <ChevronUp className="w-3.5 h-3.5" />
                </button>
                <button
                  onClick={() => moveGroupChild(field.id, index, 1)}
                  disabled={index === group.fields.length - 1}
                  title="Nach unten"
                  className="p-1 text-archive-ink/40 hover:text-archive-ink disabled:opacity-20 disabled:cursor-not-allowed"
                >
                  <ChevronDown className="w-3.5 h-3.5" />
                </button>
                <button
                  onClick={() => removeGroupChild(field.id, index)}
                  title="Feld entfernen"
                  className="p-1 text-archive-ink/30 hover:text-red-700"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </li>
            ))}
          </ul>
        )}

        <div className="flex gap-2 pt-1">
          <input
            type="text"
            value={newChild}
            onChange={(e) => setNewChild(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleAddChild();
            }}
            placeholder="Neues Feld je Eintrag, z. B. Spieldauer"
            className="flex-1 bg-parchment-light/40 border border-parchment-dark/50 rounded px-3 py-1.5 text-sm text-archive-ink focus:outline-none focus:border-archive-sepia/50"
          />
          <button
            onClick={handleAddChild}
            className="px-3 py-1.5 rounded bg-archive-sepia/80 text-parchment-light text-sm hover:bg-archive-sepia transition-colors flex items-center gap-1"
          >
            <Plus className="w-3.5 h-3.5" />
            Feld
          </button>
        </div>
      </div>

      <p className="text-[11px] text-archive-ink/45 leading-relaxed flex items-start gap-1.5">
        <Layers className="w-3 h-3 mt-0.5 shrink-0" />
        <span>
          Pro Karte können keine, eine oder mehrere Einträge erkannt werden. Im CSV-Export
          entstehen für die ersten {group.max_items} Einträge feste Spalten; weitere bleiben
          in einer Überlaufspalte erhalten.
        </span>
      </p>
    </div>
  );
};
