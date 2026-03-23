/**
 * Hook for managing feedback detail data loading and status updates.
 */

import { useCallback, useEffect, useState } from 'react';
import type { FeedbackItemWithMedia, MediaItem, Status } from '../types';
import type { FeedbackApiResult } from './useFeedbackApi';
import { useFeedbackApi } from './useFeedbackApi';

export interface UseFeedbackDetailDataResult {
  api: FeedbackApiResult;
  feedback: FeedbackItemWithMedia | null;
  loading: boolean;
  error: string | null;
  selectedMedia: MediaItem | null;
  setSelectedMedia: (m: MediaItem | null) => void;
  handleStatusChange: (newStatus: Status) => Promise<void>;
}

export function useFeedbackDetailData(
  apiUrl: string,
  feedbackId: string,
  onStatusChange?: (newStatus: Status) => void,
): UseFeedbackDetailDataResult {
  const api = useFeedbackApi({ apiUrl });
  const [feedback, setFeedback] = useState<FeedbackItemWithMedia | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedMedia, setSelectedMedia] = useState<MediaItem | null>(null);

  const loadFeedback = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setFeedback(await api.getFeedback(feedbackId));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load feedback');
    } finally {
      setLoading(false);
    }
  }, [api, feedbackId]);

  useEffect(() => { loadFeedback(); }, [loadFeedback]);

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
    [api, feedback, feedbackId, onStatusChange],
  );

  return { api, feedback, loading, error, selectedMedia, setSelectedMedia, handleStatusChange };
}
