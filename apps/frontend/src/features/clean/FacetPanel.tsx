import React, { useState, useMemo } from 'react';
import { Filter } from 'lucide-react';
import type { DisplayRow } from '../results/expandResults';
import type { FacetState } from './useCleanState';
import { TextFacet } from './TextFacet';
import { PatternFacet } from './PatternFacet';

interface FacetPanelProps {
  displayRows: DisplayRow[];
  field: string;
  facetState: FacetState;
  onFacetChange: (fs: FacetState) => void;
  facetedRowCount: number;  // rows currently passing the active facet (for display in header chip)
}

/**
 * Tab container that switches between TextFacet and PatternFacet.
 * Shows a header with a Filter icon and active-facet chip when a filter is active.
 */
export function FacetPanel({
  displayRows,
  field,
  facetState,
  onFacetChange,
  facetedRowCount,
}: FacetPanelProps) {
  const [activeTab, setActiveTab] = useState<'text' | 'pattern'>('text');

  // Compute match count for PatternFacet (parent owns computation — PatternFacet is display-only)
  // Double try/catch: outer guards against stale patternError state; inner guards new RegExp construction
  const patternMatchCount = useMemo(() => {
    if (!facetState.pattern || facetState.patternError) return displayRows.length;
    try {
      const re = new RegExp(facetState.pattern, 'u');
      return displayRows.filter(r => {
        const v = (r.editedData?.[field] ?? r.data?.[field] ?? '') as string;
        return re.test(v);
      }).length;
    } catch {
      return displayRows.length;
    }
  }, [displayRows, field, facetState.pattern, facetState.patternError]);

  const handleTextSelectionChange = (values: Set<string>) => {
    onFacetChange({ ...facetState, textValues: values });
  };

  const handlePatternChange = (pattern: string, hasError: boolean) => {
    onFacetChange({ ...facetState, pattern, patternError: hasError });
  };

  const hasFacetActive = facetState.textValues.size > 0 || !!facetState.pattern;

  return (
    <div className="border border-archive-200 rounded-lg mx-4 mt-3 overflow-hidden">
      {/* Header */}
      <div className="px-4 py-2 bg-archive-50 border-b border-archive-200 flex items-center gap-2">
        <Filter size={14} className="text-archive-500" />
        <span className="text-sm font-medium text-archive-800">Facet</span>
        {hasFacetActive && (
          <span className="ml-1 text-xs bg-amber-100 text-amber-800 rounded-full px-1.5">
            {facetedRowCount} rows
          </span>
        )}
      </div>

      {/* Tab bar */}
      <div className="flex border-b border-archive-200 px-3 bg-white">
        {(['text', 'pattern'] as const).map(tab => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-3 py-2 text-xs font-medium transition-colors border-b-2
              ${activeTab === tab
                ? 'border-archive-700 text-archive-800'
                : 'border-transparent text-archive-500 hover:text-archive-700'
              }`}
          >
            {tab === 'text' ? 'Text facet' : 'Pattern facet'}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === 'text' && (
        <TextFacet
          displayRows={displayRows}
          field={field}
          selectedValues={facetState.textValues}
          onSelectionChange={handleTextSelectionChange}
        />
      )}
      {activeTab === 'pattern' && (
        <PatternFacet
          pattern={facetState.pattern}
          patternError={facetState.patternError}
          onPatternChange={handlePatternChange}
          matchCount={patternMatchCount}
          totalCount={displayRows.length}
        />
      )}
    </div>
  );
}
