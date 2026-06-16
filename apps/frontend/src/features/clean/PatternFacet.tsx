interface PatternFacetProps {
  pattern: string;
  patternError: boolean;
  onPatternChange: (pattern: string, hasError: boolean) => void;
  matchCount: number;   // number of rows currently matching the pattern (computed by parent)
  totalCount: number;   // total rows in column
}

/**
 * Regex input filter. Filters rows whose column value matches the regex.
 * Invalid regex shows a visible error indicator — NEVER crashes.
 *
 * CRITICAL: The try { new RegExp(val, 'u') } catch { hasError = true; } guard is
 * the ONLY place regex is constructed. On error, patternError is set to true and
 * the filter falls back to "no filter" (shows all rows). The render cycle never
 * receives a thrown SyntaxError. See Research Pitfall 5.
 *
 * The matchCount prop is computed by the parent (FacetPanel) by filtering displayRows —
 * PatternFacet is display-only for the regex input.
 */
export function PatternFacet({
  pattern,
  patternError,
  onPatternChange,
  matchCount,
  totalCount,
}: PatternFacetProps) {
  return (
    <div className="px-3 py-3 flex flex-col gap-2">
      <div className="relative">
        <input
          type="text"
          value={pattern}
          onChange={(e) => {
            const val = e.target.value;
            let hasError = false;
            if (val) {
              try { new RegExp(val, 'u'); }
              catch { hasError = true; }
            }
            onPatternChange(val, hasError);
          }}
          placeholder="Regex pattern (e.g. ^\d{4}$)"
          className={`w-full text-sm border rounded px-2 py-1.5 font-mono
            ${patternError
              ? 'border-red-400 bg-red-50 text-red-800 focus:ring-red-300'
              : 'border-archive-300 bg-white text-archive-800 focus:ring-archive-300'
            } focus:outline-none focus:ring-1`}
        />
        {patternError && (
          <span className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-red-600 pointer-events-none">
            Invalid regex
          </span>
        )}
      </div>
      {pattern && !patternError && (
        <p className="text-xs text-archive-500">
          {matchCount} of {totalCount} rows match
        </p>
      )}
      {pattern && (
        <button
          onClick={() => onPatternChange('', false)}
          className="self-start text-xs text-archive-600 hover:underline"
        >
          Clear pattern
        </button>
      )}
    </div>
  );
}
