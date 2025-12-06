/**
 * Screenshot upload component with drag/drop, paste, and capture support
 */

import { useCallback, useRef, useState } from 'react';
import { useScreenCapture } from '../hooks/useScreenCapture';
import type { MediaUpload } from '../types';
import { blobToDataUrl } from '../utils/captureArea';
import { AreaSelector } from './AreaSelector';

export interface ScreenshotUploaderProps {
  screenshots: Array<MediaUpload & { _previewUrl?: string }>;
  onAdd: (screenshot: MediaUpload) => void;
  onRemove: (index: number) => void;
  compact?: boolean;
}

export function ScreenshotUploader({
  screenshots,
  onAdd,
  onRemove,
  compact = false,
}: ScreenshotUploaderProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [previewUrls, setPreviewUrls] = useState<Map<number, string>>(new Map());
  const fileInputRef = useRef<HTMLInputElement>(null);

  const {
    isSelectingArea,
    startAreaSelection,
    cancelAreaSelection,
    completeAreaSelection,
    captureFullPageScreenshot,
    processImageFile,
    isProcessing,
  } = useScreenCapture();

  // Generate preview URLs for screenshots that don't have them
  const getPreviewUrl = useCallback(
    async (index: number, screenshot: MediaUpload & { _previewUrl?: string }) => {
      if (screenshot._previewUrl) return screenshot._previewUrl;
      if (previewUrls.has(index)) return previewUrls.get(index);

      const url = await blobToDataUrl(screenshot.blob);
      setPreviewUrls((prev) => new Map(prev).set(index, url));
      return url;
    },
    [previewUrls]
  );

  const handleAreaCapture = useCallback(
    async (bounds: { x: number; y: number; width: number; height: number }) => {
      try {
        const screenshot = await completeAreaSelection(bounds);
        onAdd(screenshot);
      } catch (err) {
        console.error('Area capture failed:', err);
      }
    },
    [completeAreaSelection, onAdd]
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
      setIsDragging(false);

      const files = Array.from(e.dataTransfer.files).filter((f) =>
        f.type.startsWith('image/')
      );

      for (const file of files) {
        try {
          const screenshot = await processImageFile(file);
          onAdd(screenshot);
        } catch (err) {
          console.error('Failed to process dropped file:', err);
        }
      }
    },
    [processImageFile, onAdd]
  );

  const handlePaste = useCallback(
    async (e: React.ClipboardEvent) => {
      const items = Array.from(e.clipboardData.items);
      const imageItem = items.find((item) => item.type.startsWith('image/'));

      if (imageItem) {
        const file = imageItem.getAsFile();
        if (file) {
          try {
            const screenshot = await processImageFile(file);
            onAdd(screenshot);
          } catch (err) {
            console.error('Failed to process pasted image:', err);
          }
        }
      }
    },
    [processImageFile, onAdd]
  );

  const handleFileSelect = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(e.target.files || []);

      for (const file of files) {
        try {
          const screenshot = await processImageFile(file);
          onAdd(screenshot);
        } catch (err) {
          console.error('Failed to process selected file:', err);
        }
      }

      // Reset input
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    },
    [processImageFile, onAdd]
  );

  return (
    <div className={`ui-feedback-screenshots ${compact ? 'ui-feedback-screenshots--compact' : ''}`}>
      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        multiple
        onChange={handleFileSelect}
        style={{ display: 'none' }}
      />

      {/* Capture buttons - compact shows icons only */}
      <div className={`ui-feedback-screenshot-buttons ${compact ? 'ui-feedback-screenshot-buttons--compact' : ''}`}>
        <button
          type="button"
          className={`ui-feedback-screenshot-button ${compact ? 'ui-feedback-screenshot-button--compact' : ''}`}
          onClick={startAreaSelection}
          disabled={isProcessing}
          title="Capture area"
        >
          <CropIcon />
          {!compact && <span>Capture Area</span>}
        </button>
        <button
          type="button"
          className={`ui-feedback-screenshot-button ${compact ? 'ui-feedback-screenshot-button--compact' : ''}`}
          onClick={handleFullPageCapture}
          disabled={isProcessing}
          title="Full page capture"
        >
          <MonitorIcon />
          {!compact && <span>Full Page</span>}
        </button>
        <button
          type="button"
          className={`ui-feedback-screenshot-button ${compact ? 'ui-feedback-screenshot-button--compact' : ''}`}
          onClick={() => fileInputRef.current?.click()}
          disabled={isProcessing}
          title="Upload image"
        >
          <UploadIcon />
          {!compact && <span>Upload</span>}
        </button>
      </div>

      {/* Drop zone - only show in non-compact mode or when empty */}
      {(!compact || screenshots.length === 0) && (
        <div
          className={`ui-feedback-dropzone ${isDragging ? 'ui-feedback-dropzone--active' : ''} ${compact ? 'ui-feedback-dropzone--compact' : ''}`}
          onDragOver={(e) => {
            e.preventDefault();
            setIsDragging(true);
          }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={handleDrop}
          onPaste={handlePaste}
          tabIndex={0}
        >
          <ImageIcon />
          {!compact && <span>Drop images here, paste from clipboard, or click to upload</span>}
          {compact && <span>Drop or paste image</span>}
        </div>
      )}

      {/* Preview thumbnails */}
      {screenshots.length > 0 && (
        <div className={`ui-feedback-screenshot-previews ${compact ? 'ui-feedback-screenshot-previews--compact' : ''}`}>
          {screenshots.map((screenshot, index) => (
            <ScreenshotPreview
              key={index}
              screenshot={screenshot}
              index={index}
              onRemove={() => onRemove(index)}
              getPreviewUrl={getPreviewUrl}
              compact={compact}
            />
          ))}
        </div>
      )}

      {/* Area selector overlay */}
      {isSelectingArea && (
        <AreaSelector onCapture={handleAreaCapture} onCancel={cancelAreaSelection} />
      )}

      {/* Processing indicator */}
      {isProcessing && (
        <div className="ui-feedback-loading">
          <div className="ui-feedback-spinner" />
          {!compact && 'Processing...'}
        </div>
      )}
    </div>
  );
}

// Preview component
interface ScreenshotPreviewProps {
  screenshot: MediaUpload & { _previewUrl?: string };
  index: number;
  onRemove: () => void;
  getPreviewUrl: (index: number, screenshot: MediaUpload & { _previewUrl?: string }) => Promise<string | undefined>;
  compact?: boolean;
}

function ScreenshotPreview({
  screenshot,
  index,
  onRemove,
  getPreviewUrl,
  compact = false,
}: ScreenshotPreviewProps) {
  const [url, setUrl] = useState<string | undefined>(screenshot._previewUrl);

  // Load preview URL if not already available
  if (!url) {
    getPreviewUrl(index, screenshot).then(setUrl);
  }

  return (
    <div className={`ui-feedback-screenshot-preview ${compact ? 'ui-feedback-screenshot-preview--compact' : ''}`}>
      {url ? (
        <img src={url} alt={`Screenshot ${index + 1}`} />
      ) : (
        <div className="ui-feedback-spinner" />
      )}
      <button
        type="button"
        className="ui-feedback-screenshot-preview-delete"
        onClick={onRemove}
        title="Remove screenshot"
      >
        ×
      </button>
    </div>
  );
}

// Simple icons
function CropIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M6 2v4" />
      <path d="M6 14v4" />
      <path d="M2 6h4" />
      <path d="M14 6h4" />
      <rect x="6" y="6" width="12" height="12" />
    </svg>
  );
}

function MonitorIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="2" y="3" width="20" height="14" rx="2" />
      <line x1="8" y1="21" x2="16" y2="21" />
      <line x1="12" y1="17" x2="12" y2="21" />
    </svg>
  );
}

function UploadIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="17 8 12 3 7 8" />
      <line x1="12" y1="3" x2="12" y2="15" />
    </svg>
  );
}

function ImageIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <circle cx="8.5" cy="8.5" r="1.5" />
      <polyline points="21 15 16 10 5 21" />
    </svg>
  );
}
