/**
 * Hook for managing the feedback modal form state and submission.
 */

import { useCallback, useState } from 'react';
import type {
  FeedbackCreate,
  FeedbackItem,
  FeedbackType,
  LocationContext,
  MediaUpload,
  Priority,
} from '../types';

interface UseFeedbackFormOptions {
  locationContext: LocationContext | null;
  addMedia: (media: MediaUpload) => void;
  submitFeedback: (data: Omit<FeedbackCreate, 'app_name' | 'app_version' | 'user_agent' | 'environment' | 'git_commit' | 'git_branch' | 'hostname'>) => Promise<FeedbackItem>;
  closeModal: () => void;
}

export interface UseFeedbackFormResult {
  comment: string;
  setComment: (value: string) => void;
  feedbackType: FeedbackType;
  setFeedbackType: (value: FeedbackType) => void;
  priority: Priority;
  setPriority: (value: Priority) => void;
  isSubmitting: boolean;
  error: string | null;
  voiceNoteBlob: Blob | null;
  setVoiceNoteBlob: (blob: Blob | null) => void;
  handleSubmit: () => Promise<void>;
  handleClose: () => void;
}

function resetFormState(
  setComment: (v: string) => void,
  setFeedbackType: (v: FeedbackType) => void,
  setPriority: (v: Priority) => void,
  setVoiceNoteBlob: (v: Blob | null) => void,
): void {
  setComment('');
  setFeedbackType('bug');
  setPriority('medium');
  setVoiceNoteBlob(null);
}

export function useFeedbackForm({
  locationContext, addMedia, submitFeedback, closeModal,
}: UseFeedbackFormOptions): UseFeedbackFormResult {
  const [comment, setComment] = useState('');
  const [feedbackType, setFeedbackType] = useState<FeedbackType>('bug');
  const [priority, setPriority] = useState<Priority>('medium');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [voiceNoteBlob, setVoiceNoteBlob] = useState<Blob | null>(null);

  const handleSubmit = useCallback(async () => {
    if (!locationContext) return;
    setIsSubmitting(true);
    setError(null);
    try {
      if (voiceNoteBlob) {
        addMedia({ mediaType: 'voice_note', mimeType: voiceNoteBlob.type || 'audio/webm', fileName: `voice-note-${Date.now()}.webm`, blob: voiceNoteBlob });
      }
      await submitFeedback({
        url: locationContext.url, route: locationContext.route,
        viewport_width: locationContext.viewportWidth, viewport_height: locationContext.viewportHeight,
        click_x: locationContext.clickX, click_y: locationContext.clickY,
        css_selector: locationContext.cssSelector, xpath: locationContext.xpath,
        component_name: locationContext.componentName,
        feedback_type: feedbackType, comment: comment || undefined, priority,
      });
      resetFormState(setComment, setFeedbackType, setPriority, setVoiceNoteBlob);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to submit feedback');
    } finally {
      setIsSubmitting(false);
    }
  }, [locationContext, voiceNoteBlob, addMedia, submitFeedback, feedbackType, comment, priority]);

  const handleClose = useCallback(() => {
    resetFormState(setComment, setFeedbackType, setPriority, setVoiceNoteBlob);
    setError(null);
    closeModal();
  }, [closeModal]);

  return {
    comment, setComment, feedbackType, setFeedbackType, priority, setPriority,
    isSubmitting, error, voiceNoteBlob, setVoiceNoteBlob, handleSubmit, handleClose,
  };
}
