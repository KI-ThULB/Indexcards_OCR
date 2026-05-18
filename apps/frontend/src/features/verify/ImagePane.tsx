import React, { useEffect, useRef, useState } from 'react';

interface ImagePaneProps {
  imageUrl: string;
}

export const ImagePane: React.FC<ImagePaneProps> = ({ imageUrl }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);

  // Use refs for transform state — avoids re-renders on every frame
  const scale = useRef(1);
  const tx = useRef(0);
  const ty = useRef(0);
  const dragging = useRef(false);
  const lastMouse = useRef({ x: 0, y: 0 });

  // Hint visibility — hide after first interaction
  const [showHint, setShowHint] = useState(true);

  const applyTransform = () => {
    if (imgRef.current) {
      imgRef.current.style.transform =
        `scale(${scale.current}) translate(${tx.current}px, ${ty.current}px)`;
    }
  };

  const resetTransform = () => {
    scale.current = 1;
    tx.current = 0;
    ty.current = 0;
    applyTransform();
  };

  // Reset transform when imageUrl changes (new card selected)
  useEffect(() => {
    resetTransform();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [imageUrl]);

  // WHEEL ZOOM — must use addEventListener with { passive: false }
  // React's onWheel is passive by default in React 17+, so e.preventDefault() is ignored there
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const handleWheel = (e: WheelEvent) => {
      e.preventDefault();
      setShowHint(false);
      const factor = e.deltaY > 0 ? 0.9 : 1.1;
      scale.current = Math.max(0.5, Math.min(8, scale.current * factor));
      applyTransform();
    };

    el.addEventListener('wheel', handleWheel, { passive: false });
    return () => el.removeEventListener('wheel', handleWheel);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // DRAG PAN handlers (JSX props are fine for mouse events)
  const handleMouseDown = (e: React.MouseEvent) => {
    dragging.current = true;
    lastMouse.current = { x: e.clientX, y: e.clientY };
    document.body.style.userSelect = 'none';
    setShowHint(false);
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!dragging.current) return;
    tx.current += (e.clientX - lastMouse.current.x) / scale.current;
    ty.current += (e.clientY - lastMouse.current.y) / scale.current;
    lastMouse.current = { x: e.clientX, y: e.clientY };
    applyTransform();
  };

  const handleMouseUp = () => {
    dragging.current = false;
    document.body.style.userSelect = '';
  };

  // DOUBLE-CLICK RESET
  const handleDoubleClick = () => {
    resetTransform();
  };

  return (
    <div
      ref={containerRef}
      className="relative overflow-hidden w-full h-full bg-stone-100 cursor-grab active:cursor-grabbing select-none"
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
      onDoubleClick={handleDoubleClick}
    >
      {imageUrl ? (
        <img
          ref={imgRef}
          src={imageUrl}
          alt="Index card"
          draggable={false}
          style={{
            transformOrigin: 'center center',
            transition: 'none',
            maxWidth: 'none',
            maxHeight: 'none',
            display: 'block',
            width: '100%',
            height: '100%',
            objectFit: 'contain',
          }}
        />
      ) : (
        <div className="flex items-center justify-center w-full h-full text-archive-ink/40 font-serif italic text-sm">
          No image available
        </div>
      )}

      {/* Interaction hint — fades after first user interaction */}
      {showHint && (
        <div className="absolute bottom-2 right-2 pointer-events-none">
          <span className="text-xs text-archive-ink/50 bg-parchment/80 px-2 py-1 rounded">
            Scroll to zoom · Drag to pan · Double-click to reset
          </span>
        </div>
      )}
    </div>
  );
};
