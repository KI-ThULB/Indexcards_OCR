import React from 'react';
import { useWizardStore } from '../store/wizardStore';
import type { WizardStep } from '../store/wizardStore';
import { Upload, Settings, Play, FileText, CheckCircle2, ShieldCheck, Archive, Plus, Scissors } from 'lucide-react';
import hackBannerUrl from '../../pics/hacktheheritage_banner.png';

// Obfuscated contact info — XOR-encoded to prevent email harvesting from public repo
const _d = (c: number[]) => c.map(v => String.fromCharCode(v ^ 0x42)).join('');
const _AUTHORS: readonly { name: string; e?: readonly number[] }[] = [
  { name: 'Tom Meißner',  e: [0x36,0x2d,0x2f,0x6c,0x2f,0x27,0x2b,0x31,0x31,0x2c,0x27,0x30,0x02,0x37,0x2c,0x2b,0x6f,0x28,0x27,0x2c,0x23,0x6c,0x26,0x27] },
  { name: 'Martin Heß',   e: [0x2f,0x23,0x30,0x36,0x2b,0x2c,0x6c,0x2a,0x27,0x31,0x31,0x7a,0x77,0x02,0x25,0x2f,0x23,0x2b,0x2e,0x6c,0x21,0x2d,0x2f] },
  { name: 'Claude Code' },
];

const STEPS: { key: WizardStep; label: string; icon: React.ReactNode }[] = [
  { key: 'upload', label: '1. Upload', icon: <Upload size={18} /> },
  { key: 'configure', label: '2. Configure', icon: <Settings size={18} /> },
  { key: 'processing', label: '3. Processing', icon: <Play size={18} /> },
  { key: 'results', label: '4. Results', icon: <FileText size={18} /> },
  { key: 'verify', label: '5. Verify', icon: <ShieldCheck size={18} /> },
  { key: 'clean', label: '6. Clean', icon: <Scissors size={18} /> },
];

export const Sidebar: React.FC = () => {
  const activeStep = useWizardStore((state) => state.step);
  const view = useWizardStore((state) => state.view);
  const setView = useWizardStore((state) => state.setView);
  const setStep = useWizardStore((state) => state.setStep);
  const batchId = useWizardStore((state) => state.batchId);

  const getStepStatus = (stepKey: WizardStep) => {
    if (view === 'history') return 'pending';
    const stepOrder: WizardStep[] = ['upload', 'configure', 'processing', 'results', 'verify', 'clean'];
    const activeIndex = stepOrder.indexOf(activeStep);
    const currentIndex = stepOrder.indexOf(stepKey);

    if (currentIndex < activeIndex) return 'complete';
    if (currentIndex === activeIndex) return 'active';
    return 'pending';
  };

  const handleStepClick = (stepKey: WizardStep) => {
    // Processing is never accessible via sidebar (by design)
    if (stepKey === 'processing') return;
    // Results: allow sidebar click only when a batch is loaded (batchId set)
    if (stepKey === 'results') {
      if (batchId) {
        setStep('results');
      }
      return;
    }
    // Verify: allow sidebar click only when a batch is loaded (gated same as results)
    if (stepKey === 'verify') {
      if (batchId) {
        setStep('verify');
      }
      return;
    }
    // Clean: allow sidebar click only when a batch is loaded (gated same as results/verify)
    if (stepKey === 'clean') {
      if (batchId) {
        setStep('clean');
      }
      return;
    }
    // Upload/Configure: allow clicking completed steps to go back
    const status = getStepStatus(stepKey);
    if (status === 'complete') {
      setStep(stepKey);
    }
  };

  const resetWizard = useWizardStore((state) => state.resetWizard);

  const handleShowArchive = () => {
    setView('history');
  };

  const handleNewBatch = () => {
    resetWizard();
    setView('wizard');
  };

  return (
    <aside className="w-64 border-r border-parchment-dark overflow-y-auto shrink-0 p-4 flex flex-col gap-2">
      {/* Top actions */}
      <button
        onClick={handleNewBatch}
        className="flex items-center gap-3 px-3 py-3 rounded transition-all duration-200 w-full text-left text-archive-ink/50 hover:text-archive-ink/80 hover:bg-parchment-dark/20"
      >
        <div className="w-6 h-6 rounded-full flex items-center justify-center bg-parchment-dark/50">
          <Plus size={14} />
        </div>
        <span className="font-medium text-sm">New Batch</span>
      </button>
      <button
        onClick={handleShowArchive}
        className={`
          flex items-center gap-3 px-3 py-3 rounded transition-all duration-200 w-full text-left
          ${view === 'history'
            ? 'bg-parchment-dark text-archive-ink parchment-shadow'
            : 'text-archive-ink/50 hover:text-archive-ink/80 hover:bg-parchment-dark/20'
          }
        `}
      >
        <div className={`
          w-6 h-6 rounded-full flex items-center justify-center transition-colors
          ${view === 'history' ? 'bg-archive-sepia text-parchment' : 'bg-parchment-dark/50'}
        `}>
          <Archive size={14} />
        </div>
        <span className="font-medium text-sm">Batch Archive</span>
      </button>

      <div className="text-xs uppercase font-bold text-archive-sepia/50 mb-4 mt-2 px-2 tracking-widest">Workflow</div>

      {STEPS.map((step) => {
        const status = getStepStatus(step.key);
        const isActive = status === 'active';
        const isComplete = status === 'complete';
        const isClickable =
          (isComplete && step.key !== 'processing' && step.key !== 'results' && step.key !== 'verify' && step.key !== 'clean') ||
          (step.key === 'results' && !!batchId) ||
          (step.key === 'verify' && !!batchId) ||
          (step.key === 'clean' && !!batchId);

        return (
          <div
            key={step.key}
            onClick={isClickable ? () => handleStepClick(step.key) : undefined}
            className={`
              flex items-center gap-3 px-3 py-4 rounded transition-all duration-300
              ${isActive ? 'bg-parchment-dark text-archive-ink parchment-shadow' : 'text-archive-ink/40'}
              ${isComplete ? 'text-archive-ink/70' : ''}
              ${isClickable ? 'cursor-pointer hover:bg-parchment-dark/40 hover:text-archive-ink' : 'cursor-default'}
            `}
          >
            <div className={`
              w-6 h-6 rounded-full flex items-center justify-center transition-colors
              ${isActive ? 'bg-archive-sepia text-parchment' : 'bg-parchment-dark/50'}
              ${isComplete ? 'bg-green-700/20 text-green-700' : ''}
            `}>
              {isComplete ? <CheckCircle2 size={14} /> : step.icon}
            </div>
            <span className={`font-medium ${isActive ? 'translate-x-1' : ''} transition-transform`}>
              {step.label}
            </span>
          </div>
        );
      })}

      {/* Event banner */}
      <div className="mt-auto border-t border-parchment-dark/60 pt-4 px-1 flex flex-col gap-2">
        <span className="text-[9px] uppercase tracking-widest text-archive-ink/30 font-semibold px-1">
          A Hack the Heritage Project
        </span>
        <div className="text-xs text-archive-ink/60 px-1 leading-relaxed">
          by:
          {_AUTHORS.map((a, i) => {
            const email = a.e ? _d([...a.e]) : null;
            return (
              <React.Fragment key={i}>
                <br/>
                {a.name}{email && <>{' '}<a href={`mailto:${email}`} className="underline hover:text-archive-ink/80">{email}</a></>}
                {i < _AUTHORS.length - 1 && ','}
              </React.Fragment>
            );
          })}
        </div>
        <div className="rounded overflow-hidden border border-parchment-dark/40 opacity-70 hover:opacity-100 transition-opacity">
          <img
            src={hackBannerUrl}
            alt="Hack the Heritage"
            className="w-full h-auto block"
          />
        </div>
      </div>
    </aside>
  );
};
