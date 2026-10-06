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
  isSelectingArea: boolean;
  startAreaSelection: () => void;
  cancelAreaSelection: () => void;
  completeAreaSelection: (bounds: AreaBounds) => Promise<MediaUpload>;
  captureFullPageScreenshot: () => Promise<MediaUpload>;
  processImageFile: (file: File) => Promise<MediaUpload>;
  isProcessing: boolean;
  error: string | null;
}

type ScreenshotWithPreview = MediaUpload & { _previewUrl: string };

async function createScreenshotUpload(blob: Blob, fileName: string): Promise<ScreenshotWithPreview> {
  const resizedBlob = await resizeImage(blob);
  const previewUrl = await blobToDataUrl(resizedBlob);
  return {
    mediaType: 'screenshot', mimeType: resizedBlob.type, fileName, blob: resizedBlob, _previewUrl: previewUrl,
  } as ScreenshotWithPreview;
}

function extractErrorMessage(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

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

  const completeAreaSelection = useCallback(async (bounds: AreaBounds): Promise<MediaUpload> => {
    setIsSelectingArea(false);
    setIsProcessing(true);
    setError(null);
    try {
      const blob = await captureArea(bounds);
      return await createScreenshotUpload(blob, `screenshot-${Date.now()}.png`);
    } catch (err) {
      setError(extractErrorMessage(err, 'Failed to capture area'));
      throw err;
    } finally {
      setIsProcessing(false);
    }
  }, []);

  const captureFullPageScreenshot = useCallback(async (): Promise<MediaUpload> => {
    setIsProcessing(true);
    setError(null);
    try {
      const blob = await captureFullPage();
      return await createScreenshotUpload(blob, `screenshot-${Date.now()}.png`);
    } catch (err) {
      setError(extractErrorMessage(err, 'Failed to capture page'));
      throw err;
    } finally {
      setIsProcessing(false);
    }
  }, []);

  const processImageFile = useCallback(async (file: File): Promise<MediaUpload> => {
    setIsProcessing(true);
    setError(null);
    try {
      if (!file.type.startsWith('image/')) throw new Error('File must be an image');
      return await createScreenshotUpload(file, file.name);
    } catch (err) {
      setError(extractErrorMessage(err, 'Failed to process image'));
      throw err;
    } finally {
      setIsProcessing(false);
    }
  }, []);

  return {
    isSelectingArea, startAreaSelection, cancelAreaSelection,
    completeAreaSelection, captureFullPageScreenshot, processImageFile,
    isProcessing, error,
  };
}
