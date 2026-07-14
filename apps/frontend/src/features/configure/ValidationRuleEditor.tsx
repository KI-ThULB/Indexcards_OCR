import React, { useState, useEffect } from 'react';
import { ChevronDown, ShieldCheck } from 'lucide-react';
import type { MetadataField } from '../../store/wizardStore';
import type { FieldRule } from '../../api/batchesApi';
import { VALIDATION_PRESETS, buildPrefixPattern } from './validationPresets';

interface ValidationRuleEditorProps {
  field: MetadataField;
  onChange: (rule: FieldRule | null) => void;
  /** True when the batch-level corrector toggle is on; enables the per-field corrector checkbox. */
  correctorAvailable: boolean;
}

export const ValidationRuleEditor: React.FC<ValidationRuleEditorProps> = ({
  field,
  onChange,
  correctorAvailable,
}) => {
  const [isExpanded, setIsExpanded] = useState(false);

  // Derive controlled state from field.rule
  const rule = field.rule ?? null;
  const initialPresetId = rule?.preset_id ?? 'none';

  const [presetId, setPresetId] = useState<string>(initialPresetId);
  const [customPattern, setCustomPattern] = useState<string>(rule?.pattern ?? '');
  const [prefixInput, setPrefixInput] = useState<string>('');
  const [vocabulary, setVocabulary] = useState<string>(
    rule?.vocabulary ? rule.vocabulary.join('\n') : ''
  );
  const [fuzzyEnabled, setFuzzyEnabled] = useState<boolean>(
    rule?.fuzzy_distance != null && rule.fuzzy_distance > 0
  );
  const [fuzzyDistance, setFuzzyDistance] = useState<number>(rule?.fuzzy_distance ?? 1);
  const [correctorPerField, setCorrectorPerField] = useState<boolean>(
    rule?.corrector_enabled ?? false
  );

  // Sync from external rule changes (e.g., template load)
  useEffect(() => {
    const r = field.rule ?? null;
    const pid = r?.preset_id ?? 'none';
    setPresetId(pid);
    setCustomPattern(r?.pattern ?? '');
    setVocabulary(r?.vocabulary ? r.vocabulary.join('\n') : '');
    setFuzzyEnabled(r?.fuzzy_distance != null && r.fuzzy_distance > 0);
    setFuzzyDistance(r?.fuzzy_distance ?? 1);
    setCorrectorPerField(r?.corrector_enabled ?? false);
    // Rebuild prefix input only if preset is prefix
    if (pid === 'prefix' && r?.pattern) {
      // We can't recover the original prefix from the pattern, so leave input empty
      setPrefixInput('');
    }
  }, [field.rule]); // eslint-disable-line react-hooks/exhaustive-deps

  /** Build and emit the FieldRule whenever any local state changes. */
  const emit = (
    pid: string,
    pattern: string,
    vocab: string,
    fuzzy: boolean,
    dist: number,
    corrector: boolean,
  ) => {
    if (pid === 'none') {
      onChange(null);
      return;
    }

    const vocabLines = vocab
      .split('\n')
      .map((v) => v.trim())
      .filter(Boolean);

    const rule: FieldRule = {
      preset_id: pid,
      pattern: pid === 'vocabulary' ? null : pattern || null,
      vocabulary: pid === 'vocabulary' ? (vocabLines.length > 0 ? vocabLines : null) : null,
      fuzzy_distance: pid === 'vocabulary' && fuzzy ? dist : null,
      corrector_enabled: corrector,
    };

    onChange(rule);
  };

  const handlePresetChange = (newPid: string) => {
    setPresetId(newPid);
    const preset = VALIDATION_PRESETS.find((p) => p.id === newPid);
    const pat = preset?.hasPrefixInput
      ? buildPrefixPattern(prefixInput)
      : (preset?.pattern ?? '');
    setCustomPattern(pat);
    emit(newPid, pat, vocabulary, fuzzyEnabled, fuzzyDistance, correctorPerField);
  };

  const handleCustomPatternChange = (val: string) => {
    setCustomPattern(val);
    emit(presetId, val, vocabulary, fuzzyEnabled, fuzzyDistance, correctorPerField);
  };

  const handlePrefixChange = (val: string) => {
    setPrefixInput(val);
    const pat = buildPrefixPattern(val);
    setCustomPattern(pat);
    emit(presetId, pat, vocabulary, fuzzyEnabled, fuzzyDistance, correctorPerField);
  };

  const handleVocabChange = (val: string) => {
    setVocabulary(val);
    emit(presetId, customPattern, val, fuzzyEnabled, fuzzyDistance, correctorPerField);
  };

  const handleFuzzyEnabledChange = (checked: boolean) => {
    setFuzzyEnabled(checked);
    emit(presetId, customPattern, vocabulary, checked, fuzzyDistance, correctorPerField);
  };

  const handleFuzzyDistanceChange = (val: number) => {
    setFuzzyDistance(val);
    emit(presetId, customPattern, vocabulary, fuzzyEnabled, val, correctorPerField);
  };

  const handleCorrectorChange = (checked: boolean) => {
    setCorrectorPerField(checked);
    emit(presetId, customPattern, vocabulary, fuzzyEnabled, fuzzyDistance, checked);
  };

  const hasRule = presetId !== 'none';
  const badgeLabel = hasRule
    ? (VALIDATION_PRESETS.find((p) => p.id === presetId)?.label ?? presetId)
    : null;

  return (
    <div className="border-t border-parchment-dark/10">
      {/* Collapse header */}
      <button
        type="button"
        onClick={() => setIsExpanded((prev) => !prev)}
        className="w-full flex items-center justify-between px-6 py-2 hover:bg-parchment-dark/5 transition-colors focus:outline-none"
      >
        <span className="flex items-center gap-2 text-xs text-archive-ink/50 font-mono">
          <ShieldCheck className="w-3.5 h-3.5 text-archive-sepia/50" />
          Validation Rule
          {badgeLabel && (
            <span className="px-1.5 py-0.5 bg-archive-sepia/10 border border-archive-sepia/20 rounded text-archive-sepia/70 text-[10px]">
              {badgeLabel}
            </span>
          )}
        </span>
        <ChevronDown
          className={`w-3.5 h-3.5 text-archive-ink/30 transition-transform duration-200 ${isExpanded ? 'rotate-180' : ''}`}
        />
      </button>

      {isExpanded && (
        <div className="px-6 pb-4 pt-2 space-y-3 bg-parchment-light/20">
          {/* Preset picker */}
          <div className="flex flex-col gap-1">
            <label className="text-xs text-archive-ink/50 font-mono uppercase tracking-wide">
              Preset
            </label>
            <select
              value={presetId}
              onChange={(e) => handlePresetChange(e.target.value)}
              className="w-full bg-parchment-light/30 border border-parchment-dark/50 rounded px-3 py-1.5 font-mono text-xs text-archive-ink focus:outline-none focus:border-archive-sepia/50 transition-colors"
            >
              {VALIDATION_PRESETS.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                </option>
              ))}
            </select>
            {presetId !== 'none' && (
              <p className="text-[10px] italic text-archive-ink/40">
                {VALIDATION_PRESETS.find((p) => p.id === presetId)?.description}
              </p>
            )}
          </div>

          {/* Prefix input */}
          {presetId === 'prefix' && (
            <div className="flex flex-col gap-1">
              <label className="text-xs text-archive-ink/50 font-mono uppercase tracking-wide">
                Prefix (e.g. KMB-)
              </label>
              <input
                type="text"
                value={prefixInput}
                onChange={(e) => handlePrefixChange(e.target.value)}
                placeholder="e.g. KMB-"
                className="w-full bg-parchment-light/30 border border-parchment-dark/50 rounded px-3 py-1.5 font-mono text-xs text-archive-ink focus:outline-none focus:border-archive-sepia/50 transition-colors"
              />
              {customPattern && (
                <p className="text-[10px] font-mono text-archive-ink/30 break-all">
                  Pattern: {customPattern}
                </p>
              )}
            </div>
          )}

          {/* Custom regex input */}
          {presetId === 'custom' && (
            <div className="flex flex-col gap-1">
              <label className="text-xs text-archive-ink/50 font-mono uppercase tracking-wide">
                Regex Pattern
              </label>
              <input
                type="text"
                value={customPattern}
                onChange={(e) => handleCustomPatternChange(e.target.value)}
                placeholder="e.g. ^\d{4}$"
                className="w-full bg-parchment-light/30 border border-parchment-dark/50 rounded px-3 py-1.5 font-mono text-xs text-archive-ink focus:outline-none focus:border-archive-sepia/50 transition-colors"
              />
            </div>
          )}

          {/* Known regex preset — show the pattern as read-only info */}
          {presetId !== 'none' &&
            presetId !== 'custom' &&
            presetId !== 'prefix' &&
            presetId !== 'vocabulary' &&
            customPattern && (
              <p className="text-[10px] font-mono text-archive-ink/30 break-all">
                Pattern: {customPattern}
              </p>
            )}

          {/* Vocabulary textarea */}
          {presetId === 'vocabulary' && (
            <div className="flex flex-col gap-2">
              <label className="text-xs text-archive-ink/50 font-mono uppercase tracking-wide">
                Allowed Values (one per line)
              </label>
              <textarea
                value={vocabulary}
                onChange={(e) => handleVocabChange(e.target.value)}
                placeholder="Enter each allowed value on its own line"
                rows={5}
                className="w-full bg-parchment-light/30 border border-parchment-dark/50 rounded px-3 py-2 font-mono text-xs text-archive-ink focus:outline-none focus:border-archive-sepia/50 resize-y transition-colors"
              />

              {/* Fuzzy matching */}
              <label className="flex items-center gap-2 text-xs text-archive-ink/60 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={fuzzyEnabled}
                  onChange={(e) => handleFuzzyEnabledChange(e.target.checked)}
                  className="accent-archive-sepia"
                />
                Enable fuzzy matching (Levenshtein)
              </label>

              {fuzzyEnabled && (
                <label className="flex items-center gap-2 text-xs text-archive-ink/60 ml-5">
                  Max edit distance:
                  <input
                    type="number"
                    min={1}
                    max={5}
                    value={fuzzyDistance}
                    onChange={(e) =>
                      handleFuzzyDistanceChange(
                        Math.min(5, Math.max(1, Number(e.target.value) || 1))
                      )
                    }
                    className="w-16 bg-parchment-light/30 border border-parchment-dark/50 rounded px-2 py-1 font-mono text-xs text-archive-ink focus:outline-none focus:border-archive-sepia/50 transition-colors"
                  />
                </label>
              )}
            </div>
          )}

          {/* Per-field corrector toggle */}
          {presetId !== 'none' && (
            <div className="pt-1 border-t border-parchment-dark/10">
              <label
                className={`flex items-center gap-2 text-xs select-none ${
                  correctorAvailable
                    ? 'text-archive-ink/60 cursor-pointer'
                    : 'text-archive-ink/30 cursor-not-allowed'
                }`}
                title={
                  correctorAvailable
                    ? 'Invoke LLM corrector when this field fails validation'
                    : 'Batch-level LLM correction is off — enable it in the "How to extract" panel'
                }
              >
                <input
                  type="checkbox"
                  checked={correctorPerField}
                  disabled={!correctorAvailable}
                  onChange={(e) => handleCorrectorChange(e.target.checked)}
                  className="accent-archive-sepia disabled:opacity-40"
                />
                Enable LLM correction for this field
                {!correctorAvailable && (
                  <span className="text-[10px] italic text-archive-ink/30">
                    (batch corrector is off)
                  </span>
                )}
              </label>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
