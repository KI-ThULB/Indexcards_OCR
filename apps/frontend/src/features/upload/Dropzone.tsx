import React, { useCallback } from 'react';
import { useDropzone, type FileRejection } from 'react-dropzone';
import { Upload, Image as ImageIcon, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { useWizardStore } from '../../store/wizardStore';
import type { UploadedFile } from '../../store/wizardStore';
import { useUploadMutation } from '../../api/uploadApi';

const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10MB

export const Dropzone: React.FC = () => {
  const { files, updateFiles, sessionId, setSessionId } = useWizardStore();
  const uploadMutation = useUploadMutation();

  const onDrop = useCallback(
    (acceptedFiles: File[], fileRejections: FileRejection[]) => {
      // Handle rejections
      fileRejections.forEach((rejection) => {
        rejection.errors.forEach((err) => {
          if (err.code === 'file-too-large') {
            toast.error(`File too large: ${rejection.file.name}`, {
              description: 'Maximum size is 10MB.',
            });
          } else if (err.code === 'file-invalid-type') {
            toast.error(`Invalid file type: ${rejection.file.name}`, {
              description: 'Only JPG, PNG, and WEBP are supported.',
            });
          } else {
            toast.error(`Error with ${rejection.file.name}: ${err.message}`);
          }
        });
      });

      // Handle accepted files
      if (acceptedFiles.length > 0) {
        uploadMutation.mutate(
          { files: acceptedFiles, sessionId },
          {
            onSuccess: (data) => {
              const newFiles: UploadedFile[] = acceptedFiles.map((file) => ({
                id: Math.random().toString(36).substring(2, 11),
                name: file.name,
                size: file.size,
                type: file.type,
                preview: URL.createObjectURL(file),
              }));

              updateFiles([...files, ...newFiles]);
              setSessionId(data.session_id);
            },
          }
        );
      }
    },
    [files, updateFiles, sessionId, setSessionId, uploadMutation]
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'image/jpeg': ['.jpg', '.jpeg'],
      'image/png': ['.png'],
      'image/webp': ['.webp'],
    },
    maxSize: MAX_FILE_SIZE,
    disabled: uploadMutation.isPending,
  });

  return (
    <div
      {...getRootProps()}
      className={`
        border-2 border-dashed rounded-lg p-12 transition-all cursor-pointer
        flex flex-col items-center justify-center text-center relative
        ${
          isDragActive
            ? 'border-archive-sepia bg-parchment-light/80 scale-[1.01]'
            : 'border-parchment-dark/50 bg-parchment-light/30 hover:bg-parchment-light/50 hover:border-parchment-dark'
        }
        ${uploadMutation.isPending ? 'opacity-50 cursor-wait' : ''}
      `}
    >
      <input {...getInputProps()} />
      
      {uploadMutation.isPending && (
        <div className="absolute inset-0 flex items-center justify-center bg-parchment-light/20 backdrop-blur-sm z-20 rounded-lg">
          <div className="flex flex-col items-center">
            <Loader2 className="w-12 h-12 text-archive-sepia animate-spin mb-2" />
            <p className="text-archive-sepia font-serif italic">Syncing with Archive...</p>
          </div>
        </div>
      )}

      <div className="bg-parchment-dark/10 p-4 rounded-full mb-4">
        {isDragActive ? (
          <Upload className="w-10 h-10 text-archive-sepia animate-bounce" />
        ) : (
          <ImageIcon className="w-10 h-10 text-archive-ink/40" />
        )}
      </div>
      <h3 className="text-xl font-serif text-archive-ink mb-2">
        {isDragActive ? 'Release to stage images' : 'Stage collection items'}
      </h3>
      <p className="text-archive-ink/60 font-light italic mb-4">
        Drag and drop your index card scans here, or click to browse
      </p>
      <div className="flex gap-4 text-xs uppercase tracking-widest text-archive-ink/40">
        <span>JPG</span>
        <span>•</span>
        <span>PNG</span>
        <span>•</span>
        <span>WEBP</span>
        <span>•</span>
        <span>Max 10MB</span>
      </div>
    </div>
  );
};

