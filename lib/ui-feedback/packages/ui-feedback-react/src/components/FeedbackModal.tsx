/**
 * Main feedback modal component
 *
 * Redesigned for compact UX with badge-style dropdowns at top
 */

import { useCallback, useRef, useState } from 'react';
import { useFeedback } from '../FeedbackContext';
import type { FeedbackType, MediaUpload, Priority } from '../types';
import { ScreenshotUploader } from './ScreenshotUploader';
import { VoiceRecorder } from './VoiceRecorder';

const FEEDBACK_TYPES: { value: FeedbackType; label: string; emoji: string; color: string }[] = [
  { value: 'bug', label: 'Bug', emoji: '🐛', color: '#ef4444' },
  { value: 'feature', label: 'Feature', emoji: '✨', color: '#8b5cf6' },
  { value: 'ui_ux', label: 'UI/UX', emoji: '🎨', color: '#3b82f6' },
  { value: 'performance', label: 'Perf', emoji: '⚡', color: '#f59e0b' },
  { value: 'question', label: 'Question', emoji: '❓', color: '#6b7280' },
  { value: 'other', label: 'Other', emoji: '📝', color: '#6b7280' },
];

const PRIORITIES: { value: Priority; label: string; color: string }[] = [
  { value: 'low', label: 'Low', color: '#6b7280' },
  { value: 'medium', label: 'Medium', color: '#f59e0b' },
  { value: 'high', label: 'High', color: '#ef4444' },
  { value: 'critical', label: 'Critical', color: '#dc2626' },
];

export function FeedbackModal() {
  const {
    isOpen,
    locationContext,
    closeModal,
    addMedia,
    removeMedia,
    pendingMedia,
    submitFeedback,
  } = useFeedback();

  const [comment, setComment] = useState('');
  const [feedbackType, setFeedbackType] = useState<FeedbackType>('bug');
  const [priority, setPriority] = useState<Priority>('medium');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [voiceNoteBlob, setVoiceNoteBlob] = useState<Blob | null>(null);
  const [showTypeDropdown, setShowTypeDropdown] = useState(false);
  const [showPriorityDropdown, setShowPriorityDropdown] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleSubmit = useCallback(async () => {
    if (!locationContext) return;

    setIsSubmitting(true);
    setError(null);

    try {
      // Add voice note if exists
      if (voiceNoteBlob) {
        addMedia({
          mediaType: 'voice_note',
          mimeType: voiceNoteBlob.type || 'audio/webm',
          fileName: `voice-note-${Date.now()}.webm`,
          blob: voiceNoteBlob,
        });
      }

      await submitFeedback({
        url: locationContext.url,
        route: locationContext.route,
        viewport_width: locationContext.viewportWidth,
        viewport_height: locationContext.viewportHeight,
        click_x: locationContext.clickX,
        click_y: locationContext.clickY,
        css_selector: locationContext.cssSelector,
        xpath: locationContext.xpath,
        component_name: locationContext.componentName,
        feedback_type: feedbackType,
        comment: comment || undefined,
        priority,
      });

      // Reset form
      setComment('');
      setFeedbackType('bug');
      setPriority('medium');
      setVoiceNoteBlob(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to submit feedback');
    } finally {
      setIsSubmitting(false);
    }
  }, [
    locationContext,
    voiceNoteBlob,
    addMedia,
    submitFeedback,
    feedbackType,
    comment,
    priority,
  ]);

  const handleClose = useCallback(() => {
    setComment('');
    setFeedbackType('bug');
    setPriority('medium');
    setVoiceNoteBlob(null);
    setError(null);
    closeModal();
  }, [closeModal]);

  if (!isOpen || !locationContext) return null;

  // Filter to only screenshot media for the uploader
  const screenshots = pendingMedia.filter(
    (m) => m.mediaType === 'screenshot'
  ) as Array<MediaUpload & { _previewUrl?: string }>;

  return (
    <div className="ui-feedback-modal-overlay" onClick={handleClose}>
      <div className="ui-feedback-modal" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="ui-feedback-modal-header">
          <div className="ui-feedback-modal-header-content">
            <h2 className="ui-feedback-modal-title">Leave Feedback</h2>
            <p className="ui-feedback-modal-subtitle">{locationContext.url}</p>
          </div>
          <button
            type="button"
            className="ui-feedback-modal-close"
            onClick={handleClose}
            aria-label="Close"
          >
            <CloseIcon />
          </button>
        </div>

        {/* Body */}
        <div className="ui-feedback-modal-body">
          {/* Type and Priority badges at top */}
          <div className="ui-feedback-badge-row">
            {/* Type badge dropdown */}
            <div className="ui-feedback-badge-container">
              <button
                type="button"
                className="ui-feedback-badge ui-feedback-badge--type"
                style={{ backgroundColor: FEEDBACK_TYPES.find(t => t.value === feedbackType)?.color }}
                onClick={() => {
                  setShowTypeDropdown(!showTypeDropdown);
                  setShowPriorityDropdown(false);
                }}
              >
                <span>{FEEDBACK_TYPES.find(t => t.value === feedbackType)?.emoji}</span>
                <span>{FEEDBACK_TYPES.find(t => t.value === feedbackType)?.label}</span>
                <ChevronIcon />
              </button>
              {showTypeDropdown && (
                <div className="ui-feedback-badge-dropdown">
                  {FEEDBACK_TYPES.map((t) => (
                    <button
                      key={t.value}
                      type="button"
                      className={`ui-feedback-badge-option ${feedbackType === t.value ? 'ui-feedback-badge-option--active' : ''}`}
                      onClick={() => {
                        setFeedbackType(t.value);
                        setShowTypeDropdown(false);
                      }}
                    >
                      <span>{t.emoji}</span>
                      <span>{t.label}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* Priority badge dropdown */}
            <div className="ui-feedback-badge-container">
              <button
                type="button"
                className="ui-feedback-badge ui-feedback-badge--priority"
                style={{ backgroundColor: PRIORITIES.find(p => p.value === priority)?.color }}
                onClick={() => {
                  setShowPriorityDropdown(!showPriorityDropdown);
                  setShowTypeDropdown(false);
                }}
              >
                <span>{priority.charAt(0).toUpperCase() + priority.slice(1)}</span>
                <ChevronIcon />
              </button>
              {showPriorityDropdown && (
                <div className="ui-feedback-badge-dropdown">
                  {PRIORITIES.map((p) => (
                    <button
                      key={p.value}
                      type="button"
                      className={`ui-feedback-badge-option ${priority === p.value ? 'ui-feedback-badge-option--active' : ''}`}
                      style={{ '--badge-color': p.color } as React.CSSProperties}
                      onClick={() => {
                        setPriority(p.value);
                        setShowPriorityDropdown(false);
                      }}
                    >
                      <span className="ui-feedback-priority-dot" style={{ backgroundColor: p.color }} />
                      <span>{p.label}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* Location info (condensed) */}
            <div className="ui-feedback-location-compact">
              {locationContext.componentName && (
                <span title={`Component: ${locationContext.componentName}`}>
                  &lt;{locationContext.componentName}&gt;
                </span>
              )}
              <span title="Viewport size">
                {locationContext.viewportWidth}×{locationContext.viewportHeight}
              </span>
            </div>
          </div>

          {/* Comment input with voice recorder inline */}
          <div className="ui-feedback-section ui-feedback-section--textarea">
            <textarea
              ref={textareaRef}
              className="ui-feedback-textarea"
              placeholder="Describe the problem or suggestion... (Shift+Enter to submit)"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && e.shiftKey && !isSubmitting) {
                  e.preventDefault();
                  handleSubmit();
                }
              }}
              rows={3}
            />
            <div className="ui-feedback-textarea-actions">
              <VoiceRecorder
                onRecordingComplete={setVoiceNoteBlob}
                onDelete={() => setVoiceNoteBlob(null)}
                compact
              />
            </div>
          </div>

          {/* Screenshots (condensed) */}
          <div className="ui-feedback-section ui-feedback-section--screenshots">
            <ScreenshotUploader
              screenshots={screenshots}
              onAdd={addMedia}
              onRemove={(index) => {
                let screenshotIndex = 0;
                for (let i = 0; i < pendingMedia.length; i++) {
                  if (pendingMedia[i].mediaType === 'screenshot') {
                    if (screenshotIndex === index) {
                      removeMedia(i);
                      break;
                    }
                    screenshotIndex++;
                  }
                }
              }}
              compact
            />
          </div>

          {/* Error message */}
          {error && <div className="ui-feedback-error">{error}</div>}
        </div>

        {/* Footer */}
        <div className="ui-feedback-modal-footer">
          <button
            type="button"
            className="ui-feedback-btn ui-feedback-btn--secondary"
            onClick={handleClose}
            disabled={isSubmitting}
          >
            Cancel
          </button>
          <button
            type="button"
            className="ui-feedback-btn ui-feedback-btn--primary"
            onClick={handleSubmit}
            disabled={isSubmitting}
          >
            {isSubmitting ? (
              <>
                <div className="ui-feedback-spinner" />
                Submitting...
              </>
            ) : (
              'Submit Feedback'
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

// Simple icons
function CloseIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  );
}

function ChevronIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polyline points="6 9 12 15 18 9" />
    </svg>
  );
}
