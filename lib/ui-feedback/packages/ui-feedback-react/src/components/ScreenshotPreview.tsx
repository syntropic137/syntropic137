/**
 * Screenshot thumbnail preview with lazy-loaded preview URL
 */

import { useEffect, useState } from 'react';
import type { MediaUpload } from '../types';
import { blobToDataUrl } from '../utils/captureArea';

export interface ScreenshotPreviewProps {
  screenshot: MediaUpload & { _previewUrl?: string };
  index: number;
  onRemove: () => void;
  compact?: boolean;
}

export function ScreenshotPreview({
  screenshot,
  index,
  onRemove,
  compact = false,
}: ScreenshotPreviewProps) {
  const [url, setUrl] = useState<string | undefined>(screenshot._previewUrl);

  useEffect(() => {
    if (url) return;
    blobToDataUrl(screenshot.blob).then(setUrl);
  }, [screenshot.blob, url]);

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
        &times;
      </button>
    </div>
  );
}
