/**
 * Hook encapsulating screenshot capture/upload event handlers
 */

import { useCallback, type RefObject } from 'react';
import type { MediaUpload } from '../types';
import type { UseScreenCaptureResult } from './useScreenCapture';

interface UseScreenshotHandlersOptions {
  screenCapture: UseScreenCaptureResult;
  onAdd: (screenshot: MediaUpload) => void;
  fileInputRef: RefObject<HTMLInputElement | null>;
}

async function processAndAdd(
  processImageFile: (file: File) => Promise<MediaUpload>,
  onAdd: (screenshot: MediaUpload) => void,
  file: File,
): Promise<void> {
  try {
    const screenshot = await processImageFile(file);
    onAdd(screenshot);
  } catch (err) {
    console.error('Failed to process image file:', err);
  }
}

export function useScreenshotHandlers({ screenCapture, onAdd, fileInputRef }: UseScreenshotHandlersOptions) {
  const { completeAreaSelection, captureFullPageScreenshot, processImageFile } = screenCapture;

  const handleAreaCapture = useCallback(
    async (bounds: { x: number; y: number; width: number; height: number }) => {
      try {
        const screenshot = await completeAreaSelection(bounds);
        onAdd(screenshot);
      } catch (err) {
        console.error('Area capture failed:', err);
      }
    },
    [completeAreaSelection, onAdd],
  );

  const handleFullPageCapture = useCallback(async () => {
    try {
      const screenshot = await captureFullPageScreenshot();
      onAdd(screenshot);
    } catch (err) {
      console.error('Full page capture failed:', err);
    }
  }, [captureFullPageScreenshot, onAdd]);

  const handleDrop = useCallback(
    async (e: React.DragEvent) => {
      e.preventDefault();
      const files = Array.from(e.dataTransfer.files).filter((f) => f.type.startsWith('image/'));
      for (const file of files) {
        await processAndAdd(processImageFile, onAdd, file);
      }
    },
    [processImageFile, onAdd],
  );

  const handlePaste = useCallback(
    async (e: React.ClipboardEvent) => {
      const items = Array.from(e.clipboardData.items);
      const imageItem = items.find((item) => item.type.startsWith('image/'));
      if (!imageItem) return;
      const file = imageItem.getAsFile();
      if (file) {
        await processAndAdd(processImageFile, onAdd, file);
      }
    },
    [processImageFile, onAdd],
  );

  const handleFileSelect = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(e.target.files || []);
      for (const file of files) {
        await processAndAdd(processImageFile, onAdd, file);
      }
      if (fileInputRef.current) fileInputRef.current.value = '';
    },
    [processImageFile, onAdd, fileInputRef],
  );

  return { handleAreaCapture, handleFullPageCapture, handleDrop, handlePaste, handleFileSelect };
}
