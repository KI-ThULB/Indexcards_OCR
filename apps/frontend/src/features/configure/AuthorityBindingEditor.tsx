import { useState } from 'react';
import { ChevronDown, Link2 } from 'lucide-react';
import type { AuthorityBinding, AuthorityType } from '../../api/batchesApi';
import type { MetadataField } from '../../store/wizardStore';

interface AuthorityBindingEditorProps {
  field: MetadataField;
  onChange: (binding: AuthorityBinding | null) => void;
}

// 9 options: None + 5 GND sub-collections + 3 external authorities
const AUTHORITY_OPTIONS: Array<{ value: AuthorityType; label: string }> = [
  { value: null,                   label: 'None' },
  { value: 'gnd-persons',          label: 'GND: Persons' },
  { value: 'gnd-places',           label: 'GND: Places' },
  { value: 'gnd-subjects',         label: 'GND: Subjects' },
  { value: 'gnd-corporate-bodies', label: 'GND: Corporate Bodies' },
  { value: 'gnd-works',            label: 'GND: Works' },
  { value: 'wikidata',             label: 'Wikidata' },
  { value: 'geonames',             label: 'GeoNames' },
  { value: 'aat',                  label: 'Getty AAT' },
];

export function AuthorityBindingEditor({ field, onChange }: AuthorityBindingEditorProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const currentType = field.authority?.type ?? null;
  const currentLabel = AUTHORITY_OPTIONS.find((o) => o.value === currentType)?.label ?? 'None';

  return (
    <div className="border-t border-parchment-dark/10">
      {/* Collapse header */}
      <button
        type="button"
        onClick={() => setIsExpanded((prev) => !prev)}
        className="w-full flex items-center justify-between px-6 py-2 hover:bg-parchment-dark/5 transition-colors focus:outline-none"
      >
        <span className="flex items-center gap-2 text-xs text-archive-ink/50 font-mono">
          <Link2 className="w-3.5 h-3.5 text-archive-sepia/50" />
          Authority
          {currentType && (
            <span className="px-1.5 py-0.5 bg-blue-50 border border-blue-200 rounded text-blue-700 text-[10px] font-medium">
              {currentLabel}
            </span>
          )}
        </span>
        <ChevronDown
          className={`w-3.5 h-3.5 text-archive-ink/30 transition-transform duration-200 ${isExpanded ? 'rotate-180' : ''}`}
        />
      </button>

      {/* Expanded content */}
      {isExpanded && (
        <div className="px-6 pb-4 pt-2 space-y-2 bg-parchment-light/20">
          <div className="flex flex-col gap-1">
            <label className="text-xs text-archive-ink/50 font-mono uppercase tracking-wide">
              Authority file
            </label>
            <select
              value={currentType ?? ''}
              onChange={(e) => {
                const val = e.target.value || null;
                onChange(val ? { type: val as AuthorityType } : null);
              }}
              className="w-full bg-parchment-light/30 border border-parchment-dark/50 rounded px-3 py-1.5 font-mono text-xs text-archive-ink focus:outline-none focus:border-archive-sepia/50 transition-colors"
            >
              {AUTHORITY_OPTIONS.map((opt) => (
                <option key={opt.value ?? '_none'} value={opt.value ?? ''}>
                  {opt.label}
                </option>
              ))}
            </select>
            <p className="text-[10px] italic text-archive-ink/40">
              When set, the Clean step can reconcile this field against the authority file and emit URIs in exports.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
