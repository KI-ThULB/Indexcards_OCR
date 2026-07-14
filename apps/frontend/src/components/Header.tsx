import React from 'react';
import thuLbLogoUrl from '../../pics/ThULB_Logo_Line_Outline.svg';

export const Header: React.FC = () => {
  return (
    <header className="h-16 border-b border-parchment-dark flex items-center justify-between px-6 bg-parchment sticky top-0 z-30">
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 bg-archive-sepia rounded-sm flex items-center justify-center">
          <span className="text-parchment text-lg font-bold">A</span>
        </div>
        <h1 className="text-xl tracking-tight uppercase">Archival Metadata Extraction &amp; Export Tool</h1>
      </div>

      {/* Institutional partner logo */}
      <a
        href="https://www.thulb.uni-jena.de"
        target="_blank"
        rel="noopener noreferrer"
        title="Thüringer Universitäts- und Landesbibliothek Jena"
        className="bg-white/90 hover:bg-white transition-colors rounded px-2.5 py-1.5 flex items-center border border-parchment-dark/30 shadow-sm"
      >
        <img src={thuLbLogoUrl} alt="ThULB Jena" className="h-6 w-auto" />
      </a>
    </header>
  );
};
