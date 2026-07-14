import React, { useRef, useState } from 'react';
import { useWizardStore } from '../../store/wizardStore';

interface CockpitLayoutProps {
  left: React.ReactNode;
  right: React.ReactNode;
}

export const CockpitLayout: React.FC<CockpitLayoutProps> = ({ left, right }) => {
  const cockpitSplitPercent = useWizardStore((s) => s.cockpitSplitPercent);
  const setCockpitSplitPercent = useWizardStore((s) => s.setCockpitSplitPercent);

  // Local state for live drag — writes to Zustand only on mouseup to avoid store thrash
  const [splitPercent, setSplitPercent] = useState(cockpitSplitPercent);
  const containerRef = useRef<HTMLDivElement>(null);
  const isDragging = useRef(false);

  const handleMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    isDragging.current = true;
    document.body.style.userSelect = 'none';
    document.body.style.cursor = 'col-resize';

    const handleMouseMove = (moveEvent: MouseEvent) => {
      if (!isDragging.current || !containerRef.current) return;
      const containerRect = containerRef.current.getBoundingClientRect();
      const newPercent = ((moveEvent.clientX - containerRect.left) / containerRect.width) * 100;
      const clamped = Math.max(20, Math.min(80, newPercent));
      setSplitPercent(clamped);
    };

    const handleMouseUp = (upEvent: MouseEvent) => {
      isDragging.current = false;
      document.body.style.userSelect = '';
      document.body.style.cursor = '';
      if (containerRef.current) {
        const containerRect = containerRef.current.getBoundingClientRect();
        const newPercent = ((upEvent.clientX - containerRect.left) / containerRect.width) * 100;
        const clamped = Math.max(20, Math.min(80, newPercent));
        setSplitPercent(clamped);
        setCockpitSplitPercent(clamped);
      }
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
  };

  return (
    <div
      ref={containerRef}
      className="flex flex-row w-full flex-1 min-h-0 overflow-hidden"
      style={{ height: '100%' }}
    >
      {/* Left pane — image */}
      <div
        className="overflow-hidden shrink-0"
        style={{ width: `${splitPercent}%` }}
      >
        {left}
      </div>

      {/* Drag handle */}
      <div
        onMouseDown={handleMouseDown}
        className="w-1.5 shrink-0 cursor-col-resize bg-archive-200 hover:bg-archive-400 active:bg-archive-600 transition-colors duration-100 relative group"
        title="Drag to resize panes"
      >
        {/* Visual grip dots */}
        <div className="absolute inset-y-0 left-0 right-0 flex items-center justify-center pointer-events-none">
          <div className="flex flex-col gap-1">
            <div className="w-0.5 h-0.5 rounded-full bg-archive-ink/30" />
            <div className="w-0.5 h-0.5 rounded-full bg-archive-ink/30" />
            <div className="w-0.5 h-0.5 rounded-full bg-archive-ink/30" />
          </div>
        </div>
      </div>

      {/* Right pane — fields */}
      <div
        className="flex-1 overflow-y-auto min-w-0"
      >
        {right}
      </div>
    </div>
  );
};
