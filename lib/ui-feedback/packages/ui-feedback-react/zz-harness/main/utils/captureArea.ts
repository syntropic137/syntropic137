/**
 * Screenshot capture utilities using html2canvas
 */

import html2canvas from 'html2canvas';

export interface CaptureOptions {
  /** Capture full page vs visible viewport */
  fullPage?: boolean;
  /** Quality for JPEG output (0-1) */
  quality?: number;
  /** Output format */
  format?: 'png' | 'jpeg';
}

export interface AreaBounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

/**
 * Capture the entire visible page
 */
export async function captureFullPage(options: CaptureOptions = {}): Promise<Blob> {
  const { quality = 0.9, format = 'png' } = options;

  const canvas = await html2canvas(document.body, {
    useCORS: true,
    allowTaint: true,
    logging: false,
    // Ignore our own UI elements
    ignoreElements: (element) => {
      return element.classList?.contains('ui-feedback-root') ||
        element.classList?.contains('ui-feedback-modal-overlay') ||
        element.classList?.contains('ui-feedback-area-overlay');
    },
  });

  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => {
        if (blob) {
          resolve(blob);
        } else {
          reject(new Error('Failed to convert canvas to blob'));
        }
      },
      `image/${format}`,
      quality
    );
  });
}

/**
 * Capture a specific area of the page
 */
export async function captureArea(
  bounds: AreaBounds,
  options: CaptureOptions = {}
): Promise<Blob> {
  const { quality = 0.9, format = 'png' } = options;

  // Capture the full page first
  const canvas = await html2canvas(document.body, {
    useCORS: true,
    allowTaint: true,
    logging: false,
    ignoreElements: (element) => {
      return element.classList?.contains('ui-feedback-root') ||
        element.classList?.contains('ui-feedback-modal-overlay') ||
        element.classList?.contains('ui-feedback-area-overlay');
    },
  });

  // Create a new canvas with just the selected area
  const croppedCanvas = document.createElement('canvas');
  croppedCanvas.width = bounds.width;
  croppedCanvas.height = bounds.height;

  const ctx = croppedCanvas.getContext('2d');
  if (!ctx) {
    throw new Error('Could not get canvas context');
  }

  // Account for scroll position
  const scrollX = window.scrollX;
  const scrollY = window.scrollY;

  ctx.drawImage(
    canvas,
    bounds.x + scrollX,
    bounds.y + scrollY,
    bounds.width,
    bounds.height,
    0,
    0,
    bounds.width,
    bounds.height
  );

  return new Promise((resolve, reject) => {
    croppedCanvas.toBlob(
      (blob) => {
        if (blob) {
          resolve(blob);
        } else {
          reject(new Error('Failed to convert cropped canvas to blob'));
        }
      },
      `image/${format}`,
      quality
    );
  });
}

/**
 * Convert a File/Blob to a data URL for preview
 */
export function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}

/**
 * Resize an image blob if it exceeds max dimensions
 */
export async function resizeImage(
  blob: Blob,
  maxWidth: number = 1920,
  maxHeight: number = 1080
): Promise<Blob> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      let { width, height } = img;

      // Check if resizing is needed
      if (width <= maxWidth && height <= maxHeight) {
        resolve(blob);
        return;
      }

      // Calculate new dimensions maintaining aspect ratio
      const ratio = Math.min(maxWidth / width, maxHeight / height);
      width = Math.round(width * ratio);
      height = Math.round(height * ratio);

      // Create canvas and resize
      const canvas = document.createElement('canvas');
      canvas.width = width;
      canvas.height = height;

      const ctx = canvas.getContext('2d');
      if (!ctx) {
        reject(new Error('Could not get canvas context'));
        return;
      }

      ctx.drawImage(img, 0, 0, width, height);

      canvas.toBlob(
        (resizedBlob) => {
          if (resizedBlob) {
            resolve(resizedBlob);
          } else {
            reject(new Error('Failed to resize image'));
          }
        },
        blob.type,
        0.9
      );
    };

    img.onerror = () => reject(new Error('Failed to load image'));
    img.src = URL.createObjectURL(blob);
  });
}
