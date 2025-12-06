/**
 * Hook for screen capture functionality
 */

import { useCallback, useState } from 'react';
import type { MediaUpload } from '../types';
import {
  blobToDataUrl,
  captureArea,
  captureFullPage,
  resizeImage,
  type AreaBounds,
} from '../utils/captureArea';

export interface UseScreenCaptureResult {
  /** Whether area selection mode is active */
  isSelectingArea: boolean;
  /** Start area selection mode */
  startAreaSelection: () => void;
  /** Cancel area selection */
  cancelAreaSelection: () => void;
  /** Complete area selection with bounds */
  completeAreaSelection: (bounds: AreaBounds) => Promise<MediaUpload>;
  /** Capture full page screenshot */
  captureFullPageScreenshot: () => Promise<MediaUpload>;
  /** Process a dropped/pasted file */
  processImageFile: (file: File) => Promise<MediaUpload>;
  /** Processing state */
  isProcessing: boolean;
  /** Error message */
  error: string | null;
}

/**
 * Hook for managing screen capture
 */
export function useScreenCapture(): UseScreenCaptureResult {
  const [isSelectingArea, setIsSelectingArea] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const startAreaSelection = useCallback(() => {
    setIsSelectingArea(true);
    setError(null);
  }, []);

  const cancelAreaSelection = useCallback(() => {
    setIsSelectingArea(false);
  }, []);

  const completeAreaSelection = useCallback(
    async (bounds: AreaBounds): Promise<MediaUpload> => {
      setIsSelectingArea(false);
      setIsProcessing(true);
      setError(null);

      try {
        const blob = await captureArea(bounds);
        const resizedBlob = await resizeImage(blob);
        const previewUrl = await blobToDataUrl(resizedBlob);

        return {
          mediaType: 'screenshot',
          mimeType: resizedBlob.type,
          fileName: `screenshot-${Date.now()}.png`,
          blob: resizedBlob,
          // Store preview URL for display (not part of MediaUpload type but useful)
          _previewUrl: previewUrl,
        } as MediaUpload & { _previewUrl: string };
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to capture area';
        setError(message);
        throw err;
      } finally {
        setIsProcessing(false);
      }
    },
    []
  );

  const captureFullPageScreenshot = useCallback(async (): Promise<MediaUpload> => {
    setIsProcessing(true);
    setError(null);

    try {
      const blob = await captureFullPage();
      const resizedBlob = await resizeImage(blob);
      const previewUrl = await blobToDataUrl(resizedBlob);

      return {
        mediaType: 'screenshot',
        mimeType: resizedBlob.type,
        fileName: `screenshot-${Date.now()}.png`,
        blob: resizedBlob,
        _previewUrl: previewUrl,
      } as MediaUpload & { _previewUrl: string };
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to capture page';
      setError(message);
      throw err;
    } finally {
      setIsProcessing(false);
    }
  }, []);

  const processImageFile = useCallback(async (file: File): Promise<MediaUpload> => {
    setIsProcessing(true);
    setError(null);

    try {
      // Validate file type
      if (!file.type.startsWith('image/')) {
        throw new Error('File must be an image');
      }

      // Resize if needed
      const resizedBlob = await resizeImage(file);
      const previewUrl = await blobToDataUrl(resizedBlob);

      return {
        mediaType: 'screenshot',
        mimeType: resizedBlob.type,
        fileName: file.name,
        blob: resizedBlob,
        _previewUrl: previewUrl,
      } as MediaUpload & { _previewUrl: string };
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to process image';
      setError(message);
      throw err;
    } finally {
      setIsProcessing(false);
    }
  }, []);

  return {
    isSelectingArea,
    startAreaSelection,
    cancelAreaSelection,
    completeAreaSelection,
    captureFullPageScreenshot,
    processImageFile,
    isProcessing,
    error,
  };
}
