/**
 * Screenshot upload component with drag/drop, paste, and capture support
 */

import { useRef, useState } from 'react';
import { useScreenCapture } from '../hooks/useScreenCapture';
import { useScreenshotHandlers } from '../hooks/useScreenshotHandlers';
import type { MediaUpload } from '../types';
import { AreaSelector } from './AreaSelector';
import { CropIcon, ImageIcon, MonitorIcon, UploadIcon } from './icons';
import { ScreenshotPreview } from './ScreenshotPreview';

export interface ScreenshotUploaderProps {
  screenshots: Array<MediaUpload & { _previewUrl?: string }>;
  onAdd: (screenshot: MediaUpload) => void;
  onRemove: (index: number) => void;
  compact?: boolean;
}

export function ScreenshotUploader({ screenshots, onAdd, onRemove, compact = false }: ScreenshotUploaderProps) {
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const screenCapture = useScreenCapture();
  const { handleAreaCapture, handleFullPageCapture, handleDrop: onDrop, handlePaste, handleFileSelect } = useScreenshotHandlers({ screenCapture, onAdd, fileInputRef });

  const handleDrop = (e: React.DragEvent) => { setIsDragging(false); onDrop(e); };

  return (
    <div className={`ui-feedback-screenshots ${compact ? 'ui-feedback-screenshots--compact' : ''}`}>
      <input ref={fileInputRef} type="file" accept="image/*" multiple onChange={handleFileSelect} style={{ display: 'none' }} />

      <CaptureButtons compact={compact} onArea={screenCapture.startAreaSelection} onFullPage={handleFullPageCapture} onUpload={() => fileInputRef.current?.click()} isProcessing={screenCapture.isProcessing} />

      {(!compact || screenshots.length === 0) && (
        <ScreenshotDropZone compact={compact} isDragging={isDragging} onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }} onDragLeave={() => setIsDragging(false)} onDrop={handleDrop} onPaste={handlePaste} />
      )}

      {screenshots.length > 0 && (
        <div className={`ui-feedback-screenshot-previews ${compact ? 'ui-feedback-screenshot-previews--compact' : ''}`}>
          {screenshots.map((screenshot, index) => (
            <ScreenshotPreview key={index} screenshot={screenshot} index={index} onRemove={() => onRemove(index)} compact={compact} />
          ))}
        </div>
      )}

      {screenCapture.isSelectingArea && <AreaSelector onCapture={handleAreaCapture} onCancel={screenCapture.cancelAreaSelection} />}

      {screenCapture.isProcessing && (
        <div className="ui-feedback-loading">
          <div className="ui-feedback-spinner" />
          {!compact && 'Processing...'}
        </div>
      )}
    </div>
  );
}

function CaptureButtons({ compact, onArea, onFullPage, onUpload, isProcessing }: {
  compact: boolean; onArea: () => void; onFullPage: () => void; onUpload: () => void; isProcessing: boolean;
}) {
  const cls = compact ? 'ui-feedback-screenshot-button ui-feedback-screenshot-button--compact' : 'ui-feedback-screenshot-button';
  return (
    <div className={`ui-feedback-screenshot-buttons ${compact ? 'ui-feedback-screenshot-buttons--compact' : ''}`}>
      <button type="button" className={cls} onClick={onArea} disabled={isProcessing} title="Capture area">
        <CropIcon /> {!compact && <span>Capture Area</span>}
      </button>
      <button type="button" className={cls} onClick={onFullPage} disabled={isProcessing} title="Full page capture">
        <MonitorIcon /> {!compact && <span>Full Page</span>}
      </button>
      <button type="button" className={cls} onClick={onUpload} disabled={isProcessing} title="Upload image">
        <UploadIcon /> {!compact && <span>Upload</span>}
      </button>
    </div>
  );
}

function ScreenshotDropZone({ compact, isDragging, onDragOver, onDragLeave, onDrop, onPaste }: {
  compact: boolean; isDragging: boolean;
  onDragOver: (e: React.DragEvent) => void; onDragLeave: () => void;
  onDrop: (e: React.DragEvent) => void; onPaste: (e: React.ClipboardEvent) => void;
}) {
  return (
    <div
      className={`ui-feedback-dropzone ${isDragging ? 'ui-feedback-dropzone--active' : ''} ${compact ? 'ui-feedback-dropzone--compact' : ''}`}
      onDragOver={onDragOver} onDragLeave={onDragLeave} onDrop={onDrop} onPaste={onPaste} tabIndex={0}
    >
      <ImageIcon />
      {compact ? <span>Drop or paste image</span> : <span>Drop images here, paste from clipboard, or click to upload</span>}
    </div>
  );
}
