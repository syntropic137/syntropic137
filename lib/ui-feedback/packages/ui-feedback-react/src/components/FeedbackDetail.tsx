/**
 * Feedback detail view component
 * Shows full feedback content including media (screenshots, voice notes)
 */

import { useCallback, useEffect, useState } from 'react';
import { useFeedbackApi } from '../hooks/useFeedbackApi';
import type { FeedbackItemWithMedia, MediaItem, Status } from '../types';

export interface FeedbackDetailProps {
  apiUrl: string;
  feedbackId: string;
  onClose: () => void;
  onStatusChange?: (newStatus: Status) => void;
}

const STATUS_COLORS: Record<Status, string> = {
  open: 'var(--feedback-warning)',
  in_progress: 'var(--feedback-primary)',
  resolved: 'var(--feedback-success)',
  closed: 'var(--feedback-text-secondary)',
  wont_fix: 'var(--feedback-text-secondary)',
};

const STATUS_LABELS: Record<Status, string> = {
  open: 'Open',
  in_progress: 'In Progress',
  resolved: 'Resolved',
  closed: 'Closed',
  wont_fix: "Won't Fix",
};

const TYPE_LABELS: Record<string, string> = {
  bug: '🐛 Bug Report',
  feature: '✨ Feature Request',
  ui_ux: '🎨 UI/UX Feedback',
  performance: '⚡ Performance Issue',
  question: '❓ Question',
  other: '📝 Other',
};

const PRIORITY_COLORS: Record<string, string> = {
  low: '#6b7280',
  medium: '#f59e0b',
  high: '#ef4444',
  critical: '#dc2626',
};

export function FeedbackDetail({ apiUrl, feedbackId, onClose, onStatusChange }: FeedbackDetailProps) {
  const api = useFeedbackApi({ apiUrl });
  const [feedback, setFeedback] = useState<FeedbackItemWithMedia | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedMedia, setSelectedMedia] = useState<MediaItem | null>(null);

  const loadFeedback = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getFeedback(feedbackId);
      setFeedback(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load feedback');
    } finally {
      setLoading(false);
    }
  }, [api, feedbackId]);

  useEffect(() => {
    loadFeedback();
  }, [loadFeedback]);

  const handleStatusChange = useCallback(
    async (newStatus: Status) => {
      if (!feedback) return;
      try {
        await api.updateFeedback(feedbackId, { status: newStatus });
        setFeedback({ ...feedback, status: newStatus });
        onStatusChange?.(newStatus);
      } catch (err) {
        console.error('Failed to update status:', err);
      }
    },
    [api, feedback, feedbackId, onStatusChange]
  );

  if (loading) {
    return (
      <div className="ui-feedback-modal-overlay" onClick={onClose}>
        <div className="ui-feedback-modal ui-feedback-detail-modal" onClick={(e) => e.stopPropagation()}>
          <div className="ui-feedback-list-loading">
            <div className="ui-feedback-spinner" />
            Loading feedback...
          </div>
        </div>
      </div>
    );
  }

  if (error || !feedback) {
    return (
      <div className="ui-feedback-modal-overlay" onClick={onClose}>
        <div className="ui-feedback-modal ui-feedback-detail-modal" onClick={(e) => e.stopPropagation()}>
          <div className="ui-feedback-list-error">
            <span className="ui-feedback-error">{error || 'Feedback not found'}</span>
            <button className="ui-feedback-btn ui-feedback-btn--secondary" onClick={onClose}>
              Close
            </button>
          </div>
        </div>
      </div>
    );
  }

  const screenshots = feedback.media?.filter((m) => m.media_type === 'screenshot') || [];
  const voiceNotes = feedback.media?.filter((m) => m.media_type === 'voice_note') || [];

  return (
    <div className="ui-feedback-modal-overlay" onClick={onClose}>
      <div
        className="ui-feedback-modal ui-feedback-detail-modal"
        onClick={(e) => e.stopPropagation()}
        style={{ maxWidth: '800px', maxHeight: '90vh' }}
      >
        {/* Header */}
        <div className="ui-feedback-modal-header">
          <div className="ui-feedback-modal-header-content">
            <div className="ui-feedback-detail-badges">
              <span className="ui-feedback-detail-type-badge">
                {TYPE_LABELS[feedback.feedback_type] || '📝 Other'}
              </span>
              <span
                className="ui-feedback-detail-priority-badge"
                style={{ backgroundColor: PRIORITY_COLORS[feedback.priority] }}
              >
                {feedback.priority.toUpperCase()}
              </span>
              <span
                className="ui-feedback-detail-status-badge"
                style={{ backgroundColor: STATUS_COLORS[feedback.status] }}
              >
                {STATUS_LABELS[feedback.status]}
              </span>
            </div>
            <p className="ui-feedback-modal-subtitle">{feedback.url}</p>
          </div>
          <button
            type="button"
            className="ui-feedback-modal-close"
            onClick={onClose}
            aria-label="Close"
          >
            <CloseIcon />
          </button>
        </div>

        {/* Body */}
        <div className="ui-feedback-modal-body ui-feedback-detail-body">
          {/* Location info */}
          <div className="ui-feedback-detail-section">
            <h4 className="ui-feedback-detail-section-title">Location</h4>
            <div className="ui-feedback-detail-location">
              <div className="ui-feedback-detail-location-item">
                <span className="ui-feedback-detail-label">URL:</span>
                <span className="ui-feedback-detail-value">{feedback.url}</span>
              </div>
              <div className="ui-feedback-detail-location-item">
                <span className="ui-feedback-detail-label">Route:</span>
                <span className="ui-feedback-detail-value">{feedback.route}</span>
              </div>
              <div className="ui-feedback-detail-location-item">
                <span className="ui-feedback-detail-label">Viewport:</span>
                <span className="ui-feedback-detail-value">
                  {feedback.viewport_width} × {feedback.viewport_height}
                </span>
              </div>
              {feedback.click_x !== null && feedback.click_y !== null && (
                <div className="ui-feedback-detail-location-item">
                  <span className="ui-feedback-detail-label">Click Position:</span>
                  <span className="ui-feedback-detail-value">
                    ({feedback.click_x}, {feedback.click_y})
                  </span>
                </div>
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

          {/* Comment */}
          <div className="ui-feedback-detail-section">
            <h4 className="ui-feedback-detail-section-title">Comment</h4>
            <div className="ui-feedback-detail-comment">
              {feedback.comment || <em>No comment provided</em>}
            </div>
          </div>

          {/* Screenshots */}
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
                    onClick={() => setSelectedMedia(media)}
                  >
                    <img
                      src={api.getMediaUrl(feedbackId, media.id)}
                      alt={media.file_name}
                      className="ui-feedback-detail-thumbnail"
                    />
                    <span className="ui-feedback-detail-media-name">{media.file_name}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Voice Notes */}
          {voiceNotes.length > 0 && (
            <div className="ui-feedback-detail-section">
              <h4 className="ui-feedback-detail-section-title">
                Voice Notes ({voiceNotes.length})
              </h4>
              <div className="ui-feedback-detail-voice-notes">
                {voiceNotes.map((media) => (
                  <div key={media.id} className="ui-feedback-detail-voice-note">
                    <audio
                      controls
                      src={api.getMediaUrl(feedbackId, media.id)}
                      className="ui-feedback-detail-audio"
                    />
                    <span className="ui-feedback-detail-media-name">{media.file_name}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Metadata */}
          <div className="ui-feedback-detail-section">
            <h4 className="ui-feedback-detail-section-title">Metadata</h4>
            <div className="ui-feedback-detail-metadata">
              <div className="ui-feedback-detail-location-item">
                <span className="ui-feedback-detail-label">ID:</span>
                <code className="ui-feedback-detail-code">{feedback.id}</code>
              </div>
              <div className="ui-feedback-detail-location-item">
                <span className="ui-feedback-detail-label">App:</span>
                <span className="ui-feedback-detail-value">
                  {feedback.app_name} v{feedback.app_version}
                </span>
              </div>
              <div className="ui-feedback-detail-location-item">
                <span className="ui-feedback-detail-label">Created:</span>
                <span className="ui-feedback-detail-value">
                  {new Date(feedback.created_at).toLocaleString()}
                </span>
              </div>
              <div className="ui-feedback-detail-location-item">
                <span className="ui-feedback-detail-label">Updated:</span>
                <span className="ui-feedback-detail-value">
                  {new Date(feedback.updated_at).toLocaleString()}
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="ui-feedback-modal-footer">
          <select
            className="ui-feedback-detail-status-select"
            value={feedback.status}
            onChange={(e) => handleStatusChange(e.target.value as Status)}
          >
            <option value="open">Open</option>
            <option value="in_progress">In Progress</option>
            <option value="resolved">Resolved</option>
            <option value="closed">Closed</option>
            <option value="wont_fix">Won't Fix</option>
          </select>
          <button
            type="button"
            className="ui-feedback-btn ui-feedback-btn--primary"
            onClick={onClose}
          >
            Close
          </button>
        </div>
      </div>

      {/* Image lightbox */}
      {selectedMedia && (
        <div
          className="ui-feedback-lightbox"
          onClick={() => setSelectedMedia(null)}
        >
          <img
            src={api.getMediaUrl(feedbackId, selectedMedia.id)}
            alt={selectedMedia.file_name}
            className="ui-feedback-lightbox-image"
          />
          <button
            className="ui-feedback-lightbox-close"
            onClick={() => setSelectedMedia(null)}
          >
            <CloseIcon />
          </button>
        </div>
      )}
    </div>
  );
}

// Icons
function CloseIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  );
}
