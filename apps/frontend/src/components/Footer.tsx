import React from 'react';
import { useWizardStore } from '../store/wizardStore';

export const Footer: React.FC = () => {
  const files = useWizardStore((state) => state.files);
  const fields = useWizardStore((state) => state.fields);
  
  const totalSize = files.reduce((acc, file) => acc + file.size, 0);
  const sizeFormatted = (totalSize / (1024 * 1024)).toFixed(1);

  return (
    <footer className="h-10 border-t border-parchment-dark bg-parchment flex items-center justify-between px-6 sticky bottom-0 z-20 text-[11px] uppercase tracking-widest font-mono text-archive-ink/60">
      <div className="flex items-center gap-6">
        <span>{files.length} Files</span>
        <span className="w-px h-3 bg-parchment-dark"></span>
        <span>{sizeFormatted} MB Total</span>
        <span className="w-px h-3 bg-parchment-dark"></span>
        <span>{fields.length} Fields Active</span>
      </div>
      <div className="flex items-center gap-2">
        <span className="w-2 h-2 rounded-full bg-green-700 animate-pulse"></span>
        System Ready
      </div>
    </footer>
  );
};
