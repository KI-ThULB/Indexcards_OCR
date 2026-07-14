import React, { useRef, useState, useCallback, useEffect } from 'react';
import { useWizardStore } from '../../store/wizardStore';

const MAGNIFIER_SIZE = 220;
const ZOOM_FACTOR = 3.5;

export const ImagePreview: React.FC = () => {
  const { files } = useWizardStore();
  const containerRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const lensRef = useRef<HTMLDivElement>(null);
  const rafRef = useRef<number>(0);

  const firstFile = files[0];
  const preview = firstFile?.preview;
  const [previewBroken, setPreviewBroken] = useState(false);

  // Clean up rAF on unmount
  useEffect(() => {
    return () => cancelAnimationFrame(rafRef.current);
  }, []);

  const handleMouseMove = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    // Capture values synchronously (React pools synthetic events)
    const clientX = e.clientX;
    const clientY = e.clientY;

    cancelAnimationFrame(rafRef.current);
    rafRef.current = requestAnimationFrame(() => {
      const img = imgRef.current;
      const lens = lensRef.current;
      const canvas = canvasRef.current;
      if (!containerRef.current || !img || !lens || !canvas) return;

      const imgRect = img.getBoundingClientRect();
      const x = (clientX - imgRect.left) / imgRect.width;
      const y = (clientY - imgRect.top) / imgRect.height;

      // Hide lens when cursor is outside the actual image
      if (x < 0 || x > 1 || y < 0 || y > 1) {
        lens.style.opacity = '0';
        lens.style.visibility = 'hidden';
        return;
      }

      // Position lens via transform (compositor-only, no layout trigger)
      const containerRect = containerRef.current.getBoundingClientRect();
      const lensLeft = (clientX - containerRect.left) - MAGNIFIER_SIZE / 2;
      const lensTop = (clientY - containerRect.top) - MAGNIFIER_SIZE / 2;
      lens.style.transform = `translate3d(${lensLeft}px, ${lensTop}px, 0)`;
      lens.style.opacity = '1';
      lens.style.visibility = 'visible';

      // Draw only the visible zoomed region to canvas (220x220 pixels)
      // Scale source region so ZOOM_FACTOR is relative to rendered size, not natural size
      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      const scaleX = img.naturalWidth / imgRect.width;
      const scaleY = img.naturalHeight / imgRect.height;
      const sourceW = (MAGNIFIER_SIZE / ZOOM_FACTOR) * scaleX;
      const sourceH = (MAGNIFIER_SIZE / ZOOM_FACTOR) * scaleY;
      const sx = x * img.naturalWidth - sourceW / 2;
      const sy = y * img.naturalHeight - sourceH / 2;
      ctx.clearRect(0, 0, MAGNIFIER_SIZE, MAGNIFIER_SIZE);
      ctx.drawImage(img, sx, sy, sourceW, sourceH, 0, 0, MAGNIFIER_SIZE, MAGNIFIER_SIZE);
    });
  }, []);

  const handleMouseLeave = useCallback(() => {
    cancelAnimationFrame(rafRef.current);
    if (lensRef.current) {
      lensRef.current.style.opacity = '0';
      lensRef.current.style.visibility = 'hidden';
    }
  }, []);

  if (!firstFile) return null;

  return (
    <div className="space-y-2">
      <p className="text-xs uppercase tracking-widest text-archive-ink/40 font-semibold">
        Sample Card Preview
      </p>

      <div
        ref={containerRef}
        className="relative rounded border border-parchment-dark/50 bg-parchment-light/30 parchment-shadow cursor-crosshair"
        onMouseMove={handleMouseMove}
        onMouseLeave={handleMouseLeave}
      >
        {preview && !previewBroken ? (
          <>
            <img
              ref={imgRef}
              src={preview}
              alt={firstFile.name}
              className="w-full max-h-[500px] object-contain rounded"
              onError={() => setPreviewBroken(true)}
            />

            {/* Magnifier lens — always mounted, zero React re-renders during mouse movement */}
            <div
              ref={lensRef}
              className="absolute top-0 left-0 pointer-events-none rounded-full border-2 border-archive-sepia/60 overflow-hidden shadow-lg z-10"
              style={{
                width: MAGNIFIER_SIZE,
                height: MAGNIFIER_SIZE,
                opacity: 0,
                visibility: 'hidden' as const,
                willChange: 'transform, opacity',
              }}
            >
              <canvas
                ref={canvasRef}
                width={MAGNIFIER_SIZE}
                height={MAGNIFIER_SIZE}
                className="w-full h-full"
              />
            </div>
          </>
        ) : (
          <div className="flex items-center justify-center p-8 text-archive-ink/30 italic text-sm font-serif">
            Image preview unavailable
          </div>
        )}
      </div>

      <p className="text-xs text-archive-ink/40 italic font-light">
        {firstFile.name} — hover to magnify
      </p>
    </div>
  );
};
