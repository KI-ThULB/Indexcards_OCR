import React from 'react';
import { Trash2, FileImage } from 'lucide-react';
import { toast } from 'sonner';
import { useWizardStore } from '../../store/wizardStore';

export const FileList: React.FC = () => {
  const { files, removeFile } = useWizardStore();

  const formatSize = (bytes: number) => {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  const handleDelete = (id: string, name: string) => {
    toast(`Remove ${name}?`, {
      duration: Infinity,
      action: {
        label: 'Confirm',
        onClick: () => {
          removeFile(id);
          toast.success(`${name} removed from batch.`);
        },
      },
      cancel: {
        label: 'Cancel',
        onClick: () => {},
      },
    });
  };

  if (files.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center p-12 text-archive-ink/30 border border-dashed border-parchment-dark/50 rounded-lg bg-parchment-light/10 italic">
        No collection items staged yet.
      </div>
    );
  }

  return (
    <div className="bg-parchment-light/30 border border-parchment-dark/50 rounded-lg overflow-hidden parchment-shadow">
      <div className="max-h-[400px] overflow-y-auto custom-scrollbar">
        <table className="w-full text-left border-collapse">
          <thead className="sticky top-0 bg-parchment-dark/10 backdrop-blur-sm z-10 border-b border-parchment-dark/30">
            <tr>
              <th className="px-6 py-4 text-xs uppercase tracking-widest text-archive-ink/40 font-semibold">Item</th>
              <th className="px-6 py-4 text-xs uppercase tracking-widest text-archive-ink/40 font-semibold text-right">Size</th>
              <th className="px-6 py-4 text-xs uppercase tracking-widest text-archive-ink/40 font-semibold text-right w-20">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-parchment-dark/20">
            {files.map((file) => (
              <tr key={file.id} className="hover:bg-parchment-dark/5 transition-colors group">
                <td className="px-6 py-4">
                  <div className="flex items-center gap-3">
                    <div className="p-2 bg-parchment-dark/10 rounded border border-parchment-dark/20">
                      <FileImage className="w-5 h-5 text-archive-sepia/60" />
                    </div>
                    <div className="flex flex-col min-w-0">
                      <span className="text-archive-ink font-medium truncate max-w-[300px]" title={file.name}>
                        {file.name}
                      </span>
                      <span className="text-xs text-archive-ink/40 uppercase tracking-tighter">
                        {file.type.split('/')[1] || 'Unknown'}
                      </span>
                    </div>
                  </div>
                </td>
                <td className="px-6 py-4 text-right text-sm text-archive-ink/60 font-mono">
                  {formatSize(file.size)}
                </td>
                <td className="px-6 py-4 text-right">
                  <button
                    onClick={() => handleDelete(file.id, file.name)}
                    className="p-2 text-archive-ink/30 hover:text-red-600 hover:bg-red-50 rounded-full transition-all group-hover:scale-110"
                    title="Remove item"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};
