import React from 'react';
import { useBulkStore } from '../../store/bulkStore';
import { BulkProgressStep } from './BulkProgressStep';
import { BulkStartStep } from './BulkStartStep';
import { BulkSummary } from './BulkSummary';

/**
 * The bulk workflow's own little router: start → progress → summary.
 *
 * Kept entirely separate from the interactive wizard's step machine, so the
 * standard Upload → Configure → Processing → QC → Results → Verify → Clean →
 * Export flow is untouched.
 */
export const BulkView: React.FC = () => {
  const step = useBulkStore((state) => state.step);

  switch (step) {
    case 'progress':
      return <BulkProgressStep />;
    case 'summary':
      return <BulkSummary />;
    case 'start':
    default:
      return <BulkStartStep />;
  }
};
