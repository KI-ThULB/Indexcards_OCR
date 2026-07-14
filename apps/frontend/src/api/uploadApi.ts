import axios from 'axios';
import { useMutation } from '@tanstack/react-query';
import { toast } from 'sonner';

// Define the API response schema matching the backend
export interface UploadResponse {
  session_id: string;
  filenames: string[];
  message: string;
}

// Function to upload files
const uploadFiles = async (files: File[], sessionId?: string | null): Promise<UploadResponse> => {
  const formData = new FormData();
  
  files.forEach((file) => {
    formData.append('files', file);
  });

  if (sessionId) {
    formData.append('session_id', sessionId);
  }

  // Ensure this matches the FastAPI development URL
  const response = await axios.post<UploadResponse>('/api/v1/upload/', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  });

  return response.data;
};

// Custom hook to use the upload mutation
export const useUploadMutation = () => {
  return useMutation({
    mutationFn: ({ files, sessionId }: { files: File[]; sessionId?: string | null }) => 
      uploadFiles(files, sessionId),
    onSuccess: (data) => {
      toast.success(data.message);
    },
    onError: (error: Error & { response?: { data?: { detail?: string } } }) => {
      const errorMessage = error.response?.data?.detail || 'Failed to upload files.';
      toast.error(errorMessage);
    },
  });
};
