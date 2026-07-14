import React from 'react';
import { ArrowRight, Info } from 'lucide-react';
import { useWizardStore } from '../../store/wizardStore';
import { Dropzone } from './Dropzone';
import { FileList } from './FileList';
import { WizardNav } from '../../components/WizardNav';

export const UploadStep: React.FC = () => {
  const { files, setStep } = useWizardStore();

  const handleNext = () => {
    if (files.length > 0) {
      setStep('configure');
    }
  };

  return (
    <div className="flex-1 max-w-5xl mx-auto w-full space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-700">
      <div className="flex flex-col gap-2">
        <h2 className="text-3xl font-serif text-archive-sepia">Stage Collection Items</h2>
        <p className="text-archive-ink/60 italic font-light">
          Begin by staging your index card scans for processing.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
        <div className="lg:col-span-12">
          <Dropzone />
        </div>

        <div className="lg:col-span-12 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-xl font-serif text-archive-ink">Batch Contents</h3>
            <div className="flex items-center gap-2 text-xs text-archive-ink/40 uppercase tracking-widest">
              <Info className="w-3 h-3" />
              <span>Items are stored temporarily until processing</span>
            </div>
          </div>

          <FileList />
        </div>
      </div>

      <WizardNav
        next={{
          label: 'Proceed to Configuration',
          onClick: handleNext,
          disabled: files.length === 0,
          icon: <ArrowRight className="w-5 h-5" />,
        }}
      />
    </div>
  );
};
