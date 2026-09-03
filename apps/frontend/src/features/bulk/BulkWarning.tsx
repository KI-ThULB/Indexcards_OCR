import React from 'react';
import { AlertTriangle } from 'lucide-react';

/**
 * The standing caveat for bulk mode. Shown before a run starts and again on the
 * progress view, because the whole point of the mode is that nobody is watching
 * the intermediate results.
 */
export const BulkWarning: React.FC = () => (
  <div className="flex gap-3 p-4 rounded border border-amber-700/40 bg-amber-700/5">
    <AlertTriangle className="w-5 h-5 text-amber-700 shrink-0 mt-0.5" />
    <p className="text-sm text-archive-ink/80 leading-relaxed">
      Bulk mode is intended for homogeneous collections with a previously tested
      extraction template. Intermediate manual quality control is skipped.
      Results should be validated before publication or ingest into
      authoritative systems.
    </p>
  </div>
);
