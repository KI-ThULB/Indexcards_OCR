import React from 'react';
import { Image } from 'lucide-react';

interface ThumbnailCellProps {
  batchName: string;
  filename: string;
  onOpenLightbox: (imageUrl: string) => void;
}

export const ThumbnailCell: React.FC<ThumbnailCellProps> = ({ batchName, filename, onOpenLightbox }) => {
  const imageUrl = `/batches-static/${batchName}/${filename}`;

  return (
    <button
      type="button"
      onClick={() => onOpenLightbox(imageUrl)}
      className="font-mono text-xs text-archive-sepia hover:text-archive-sepia/80 hover:underline cursor-pointer flex items-center gap-1.5 max-w-[120px] truncate"
      title={filename}
    >
      <Image className="w-4 h-4 shrink-0" />
      <span className="truncate">{filename}</span>
    </button>
  );
};
