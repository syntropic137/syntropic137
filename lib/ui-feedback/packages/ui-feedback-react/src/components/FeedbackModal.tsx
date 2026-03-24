/**
 * Main feedback modal component
 *
 * Redesigned for compact UX with badge-style dropdowns at top
 */

import { useRef } from 'react';
import { FEEDBACK_TYPES, PRIORITIES } from '../constants/statusMeta';
import { useFeedback } from '../FeedbackContext';
import { useFeedbackForm } from '../hooks/useFeedbackForm';
import type { FeedbackType, MediaUpload, Priority } from '../types';
import { BadgeDropdown } from './BadgeDropdown';
import { CloseIcon } from './icons';
import { ScreenshotUploader } from './ScreenshotUploader';
import { VoiceRecorder } from './VoiceRecorder';

export function FeedbackModal() {
  const { isOpen, locationContext, closeModal, addMedia, removeMedia, pendingMedia, submitFeedback } = useFeedback();
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const form = useFeedbackForm({ locationContext, addMedia, submitFeedback, closeModal });

  if (!isOpen || !locationContext) return null;

  const screenshots = pendingMedia.filter((m) => m.mediaType === 'screenshot') as Array<MediaUpload & { _previewUrl?: string }>;

  return (
    <div className="ui-feedback-modal-overlay" onClick={form.handleClose}>
      <div className="ui-feedback-modal" onClick={(e) => e.stopPropagation()}>
        <div className="ui-feedback-modal-header">
          <div className="ui-feedback-modal-header-content">
            <h2 className="ui-feedback-modal-title">Leave Feedback</h2>
            <p className="ui-feedback-modal-subtitle">{locationContext.url}</p>
          </div>
          <button type="button" className="ui-feedback-modal-close" onClick={form.handleClose} aria-label="Close"><CloseIcon /></button>
        </div>

        <div className="ui-feedback-modal-body">
          <div className="ui-feedback-badge-row">
            <BadgeDropdown options={FEEDBACK_TYPES} value={form.feedbackType} onChange={(v) => form.setFeedbackType(v as FeedbackType)} className="ui-feedback-badge--type" />
            <BadgeDropdown options={PRIORITIES} value={form.priority} onChange={(v) => form.setPriority(v as Priority)} className="ui-feedback-badge--priority" />
            <div className="ui-feedback-location-compact">
              {locationContext.componentName && <span title={`Component: ${locationContext.componentName}`}>&lt;{locationContext.componentName}&gt;</span>}
              <span title="Viewport size">{locationContext.viewportWidth}&times;{locationContext.viewportHeight}</span>
            </div>
          </div>

          <div className="ui-feedback-section ui-feedback-section--textarea">
            <textarea
              ref={textareaRef} className="ui-feedback-textarea"
              placeholder="Describe the problem or suggestion... (Shift+Enter to submit)"
              value={form.comment} onChange={(e) => form.setComment(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && e.shiftKey && !form.isSubmitting) { e.preventDefault(); form.handleSubmit(); } }}
              rows={3}
            />
            <div className="ui-feedback-textarea-actions">
              <VoiceRecorder onRecordingComplete={form.setVoiceNoteBlob} onDelete={() => form.setVoiceNoteBlob(null)} compact />
            </div>
          </div>

          <ScreenshotSection screenshots={screenshots} onAdd={addMedia} pendingMedia={pendingMedia} onRemove={removeMedia} />

          {form.error && <div className="ui-feedback-error">{form.error}</div>}
        </div>

        <div className="ui-feedback-modal-footer">
          <button type="button" className="ui-feedback-btn ui-feedback-btn--secondary" onClick={form.handleClose} disabled={form.isSubmitting}>Cancel</button>
          <button type="button" className="ui-feedback-btn ui-feedback-btn--primary" onClick={form.handleSubmit} disabled={form.isSubmitting}>
            {form.isSubmitting ? (<><div className="ui-feedback-spinner" /> Submitting...</>) : 'Submit Feedback'}
          </button>
        </div>
      </div>
    </div>
  );
}

function ScreenshotSection({ screenshots, onAdd, pendingMedia, onRemove }: {
  screenshots: Array<MediaUpload & { _previewUrl?: string }>;
  onAdd: (media: MediaUpload) => void;
  pendingMedia: MediaUpload[];
  onRemove: (index: number) => void;
}) {
  return (
    <div className="ui-feedback-section ui-feedback-section--screenshots">
      <ScreenshotUploader
        screenshots={screenshots} onAdd={onAdd}
        onRemove={(index) => {
          let screenshotIndex = 0;
          for (let i = 0; i < pendingMedia.length; i++) {
            if (pendingMedia[i].mediaType === 'screenshot') {
              if (screenshotIndex === index) { onRemove(i); break; }
              screenshotIndex++;
            }
          }
        }}
        compact
      />
    </div>
  );
}
