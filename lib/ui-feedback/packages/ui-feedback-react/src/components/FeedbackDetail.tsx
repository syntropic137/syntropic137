/**
 * Feedback detail view component
 * Shows full feedback content including media (screenshots, voice notes)
 */

import { PRIORITY_COLORS, STATUS_COLORS, STATUS_LABELS, TYPE_LABELS } from '../constants/statusMeta';
import { useFeedbackDetailData } from '../hooks/useFeedbackDetailData';
import type { Status } from '../types';
import { LocationSection, MediaSection, MetadataSection } from './FeedbackDetailSections';
import { CloseIcon } from './icons';
import { MediaLightbox } from './MediaLightbox';

export interface FeedbackDetailProps {
  apiUrl: string;
  feedbackId: string;
  onClose: () => void;
  onStatusChange?: (newStatus: Status) => void;
}

export function FeedbackDetail({ apiUrl, feedbackId, onClose, onStatusChange }: FeedbackDetailProps) {
  const { api, feedback, loading, error, selectedMedia, setSelectedMedia, handleStatusChange } =
    useFeedbackDetailData(apiUrl, feedbackId, onStatusChange);

  if (loading) {
    return (
      <DetailOverlay onClose={onClose}>
        <div className="ui-feedback-list-loading"><div className="ui-feedback-spinner" /> Loading feedback...</div>
      </DetailOverlay>
    );
  }

  if (error || !feedback) {
    return (
      <DetailOverlay onClose={onClose}>
        <div className="ui-feedback-list-error">
          <span className="ui-feedback-error">{error || 'Feedback not found'}</span>
          <button className="ui-feedback-btn ui-feedback-btn--secondary" onClick={onClose}>Close</button>
        </div>
      </DetailOverlay>
    );
  }

  const screenshots = feedback.media?.filter((m) => m.media_type === 'screenshot') || [];
  const voiceNotes = feedback.media?.filter((m) => m.media_type === 'voice_note') || [];

  return (
    <div className="ui-feedback-modal-overlay" onClick={onClose}>
      <div className="ui-feedback-modal ui-feedback-detail-modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '800px', maxHeight: '90vh' }}>
        <DetailHeader feedback={feedback} onClose={onClose} />

        <div className="ui-feedback-modal-body ui-feedback-detail-body">
          <LocationSection feedback={feedback} />
          <div className="ui-feedback-detail-section">
            <h4 className="ui-feedback-detail-section-title">Comment</h4>
            <div className="ui-feedback-detail-comment">{feedback.comment || <em>No comment provided</em>}</div>
          </div>
          <MediaSection feedbackId={feedbackId} screenshots={screenshots} voiceNotes={voiceNotes} getMediaUrl={api.getMediaUrl} onScreenshotClick={setSelectedMedia} />
          <MetadataSection feedback={feedback} />
        </div>

        <div className="ui-feedback-modal-footer">
          <select className="ui-feedback-detail-status-select" value={feedback.status} onChange={(e) => handleStatusChange(e.target.value as Status)}>
            <option value="open">Open</option><option value="in_progress">In Progress</option>
            <option value="resolved">Resolved</option><option value="closed">Closed</option>
            <option value="wont_fix">Won't Fix</option>
          </select>
          <button type="button" className="ui-feedback-btn ui-feedback-btn--primary" onClick={onClose}>Close</button>
        </div>
      </div>

      {selectedMedia && <MediaLightbox src={api.getMediaUrl(feedbackId, selectedMedia.id)} alt={selectedMedia.file_name || 'Screenshot'} onClose={() => setSelectedMedia(null)} />}
    </div>
  );
}

function DetailOverlay({ onClose, children }: { onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="ui-feedback-modal-overlay" onClick={onClose}>
      <div className="ui-feedback-modal ui-feedback-detail-modal" onClick={(e) => e.stopPropagation()}>
        {children}
      </div>
    </div>
  );
}

function DetailHeader({ feedback, onClose }: { feedback: { feedback_type: string; priority: string; status: string; url: string }; onClose: () => void }) {
  return (
    <div className="ui-feedback-modal-header">
      <div className="ui-feedback-modal-header-content">
        <div className="ui-feedback-detail-badges">
          <span className="ui-feedback-detail-type-badge">{TYPE_LABELS[feedback.feedback_type] || '\u{1F4DD} Other'}</span>
          <span className="ui-feedback-detail-priority-badge" style={{ backgroundColor: PRIORITY_COLORS[feedback.priority] }}>{feedback.priority.toUpperCase()}</span>
          <span className="ui-feedback-detail-status-badge" style={{ backgroundColor: STATUS_COLORS[feedback.status] }}>{STATUS_LABELS[feedback.status]}</span>
        </div>
        <p className="ui-feedback-modal-subtitle">{feedback.url}</p>
      </div>
      <button type="button" className="ui-feedback-modal-close" onClick={onClose} aria-label="Close"><CloseIcon /></button>
    </div>
  );
}
