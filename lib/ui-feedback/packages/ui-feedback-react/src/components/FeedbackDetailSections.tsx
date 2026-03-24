/**
 * Display sections for the feedback detail view
 */

import type { FeedbackItemWithMedia, MediaItem } from '../types';

// --- Location Section ---

interface LocationSectionProps {
  feedback: FeedbackItemWithMedia;
}

export function LocationSection({ feedback }: LocationSectionProps) {
  return (
    <div className="ui-feedback-detail-section">
      <h4 className="ui-feedback-detail-section-title">Location</h4>
      <div className="ui-feedback-detail-location">
        <DetailItem label="URL:" value={feedback.url} />
        <DetailItem label="Route:" value={feedback.route} />
        <DetailItem label="Viewport:" value={`${feedback.viewport_width} \u00D7 ${feedback.viewport_height}`} />
        {feedback.click_x !== null && feedback.click_y !== null && (
          <DetailItem label="Click Position:" value={`(${feedback.click_x}, ${feedback.click_y})`} />
        )}
        {feedback.component_name && (
          <div className="ui-feedback-detail-location-item">
            <span className="ui-feedback-detail-label">Component:</span>
            <span className="ui-feedback-detail-value ui-feedback-detail-component">
              &lt;{feedback.component_name}&gt;
            </span>
          </div>
        )}
        {feedback.css_selector && (
          <div className="ui-feedback-detail-location-item">
            <span className="ui-feedback-detail-label">CSS Selector:</span>
            <code className="ui-feedback-detail-code">{feedback.css_selector}</code>
          </div>
        )}
      </div>
    </div>
  );
}

// --- Media Section ---

interface MediaSectionProps {
  feedbackId: string;
  screenshots: MediaItem[];
  voiceNotes: MediaItem[];
  getMediaUrl: (feedbackId: string, mediaId: string) => string;
  onScreenshotClick: (media: MediaItem) => void;
}

export function MediaSection({
  feedbackId,
  screenshots,
  voiceNotes,
  getMediaUrl,
  onScreenshotClick,
}: MediaSectionProps) {
  return (
    <>
      {screenshots.length > 0 && (
        <div className="ui-feedback-detail-section">
          <h4 className="ui-feedback-detail-section-title">
            Screenshots ({screenshots.length})
          </h4>
          <div className="ui-feedback-detail-media-grid">
            {screenshots.map((media) => (
              <div
                key={media.id}
                className="ui-feedback-detail-media-item"
                onClick={() => onScreenshotClick(media)}
              >
                <img
                  src={getMediaUrl(feedbackId, media.id)}
                  alt={media.file_name}
                  className="ui-feedback-detail-thumbnail"
                />
                <span className="ui-feedback-detail-media-name">{media.file_name}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      {voiceNotes.length > 0 && (
        <div className="ui-feedback-detail-section">
          <h4 className="ui-feedback-detail-section-title">
            Voice Notes ({voiceNotes.length})
          </h4>
          <div className="ui-feedback-detail-voice-notes">
            {voiceNotes.map((media) => (
              <div key={media.id} className="ui-feedback-detail-voice-note">
                <audio controls src={getMediaUrl(feedbackId, media.id)} className="ui-feedback-detail-audio" />
                <span className="ui-feedback-detail-media-name">{media.file_name}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );
}

// --- Metadata Section ---

interface MetadataSectionProps {
  feedback: FeedbackItemWithMedia;
}

export function MetadataSection({ feedback }: MetadataSectionProps) {
  return (
    <div className="ui-feedback-detail-section">
      <h4 className="ui-feedback-detail-section-title">Metadata</h4>
      <div className="ui-feedback-detail-metadata">
        <div className="ui-feedback-detail-location-item">
          <span className="ui-feedback-detail-label">ID:</span>
          <code className="ui-feedback-detail-code">{feedback.id}</code>
        </div>
        <DetailItem label="App:" value={`${feedback.app_name} v${feedback.app_version}`} />
        <DetailItem label="Created:" value={new Date(feedback.created_at).toLocaleString()} />
        <DetailItem label="Updated:" value={new Date(feedback.updated_at).toLocaleString()} />
      </div>
    </div>
  );
}

// --- Shared helper ---

function DetailItem({ label, value }: { label: string; value?: string | number | null }) {
  return (
    <div className="ui-feedback-detail-location-item">
      <span className="ui-feedback-detail-label">{label}</span>
      <span className="ui-feedback-detail-value">{value}</span>
    </div>
  );
}
