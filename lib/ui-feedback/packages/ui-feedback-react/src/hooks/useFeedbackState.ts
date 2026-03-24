/**
 * Hook that holds all feedback state and callbacks for FeedbackProvider.
 */

import { useCallback, useState } from 'react';
import type {
  FeedbackCreate,
  FeedbackItem,
  FeedbackState,
  LocationContext,
  MediaUpload,
} from '../types';
import type { FeedbackApiResult } from './useFeedbackApi';

export interface UseFeedbackStateOptions {
  api: FeedbackApiResult;
  appName: string;
  appVersion?: string;
  environment?: string;
  gitCommit?: string;
  gitBranch?: string;
  hostname?: string;
  disabled?: boolean;
}

export interface UseFeedbackStateResult {
  state: FeedbackState;
  openFeedbackMode: () => void;
  closeFeedbackMode: () => void;
  openModal: (context: LocationContext) => void;
  closeModal: () => void;
  addMedia: (media: MediaUpload) => void;
  removeMedia: (index: number) => void;
  clearMedia: () => void;
  submitFeedback: (data: Omit<FeedbackCreate, 'app_name' | 'app_version' | 'user_agent' | 'environment' | 'git_commit' | 'git_branch' | 'hostname'>) => Promise<FeedbackItem>;
}

export function useFeedbackState({
  api, appName, appVersion, environment, gitCommit, gitBranch, hostname, disabled,
}: UseFeedbackStateOptions): UseFeedbackStateResult {
  const [state, setState] = useState<FeedbackState>({
    isOpen: false, isFeedbackMode: false, locationContext: null, pendingMedia: [],
  });

  const openFeedbackMode = useCallback(() => {
    if (disabled) return;
    setState((prev) => ({ ...prev, isFeedbackMode: true }));
  }, [disabled]);

  const closeFeedbackMode = useCallback(() => {
    setState((prev) => ({ ...prev, isFeedbackMode: false }));
  }, []);

  const openModal = useCallback((context: LocationContext) => {
    setState((prev) => ({ ...prev, isOpen: true, isFeedbackMode: false, locationContext: context }));
  }, []);

  const closeModal = useCallback(() => {
    setState((prev) => ({ ...prev, isOpen: false, locationContext: null, pendingMedia: [] }));
  }, []);

  const addMedia = useCallback((media: MediaUpload) => {
    setState((prev) => ({ ...prev, pendingMedia: [...prev.pendingMedia, media] }));
  }, []);

  const removeMedia = useCallback((index: number) => {
    setState((prev) => ({ ...prev, pendingMedia: prev.pendingMedia.filter((_, i) => i !== index) }));
  }, []);

  const clearMedia = useCallback(() => {
    setState((prev) => ({ ...prev, pendingMedia: [] }));
  }, []);

  const submitFeedback = useCallback(
    async (data: Omit<FeedbackCreate, 'app_name' | 'app_version' | 'user_agent' | 'environment' | 'git_commit' | 'git_branch' | 'hostname'>): Promise<FeedbackItem> => {
      const item = await api.createFeedback({
        ...data,
        app_name: appName,
        app_version: appVersion,
        user_agent: typeof navigator !== 'undefined' ? navigator.userAgent : undefined,
        environment, git_commit: gitCommit, git_branch: gitBranch, hostname,
      });

      for (const media of state.pendingMedia) {
        await api.uploadMedia(item.id, media);
      }

      closeModal();
      return item;
    },
    [api, appName, appVersion, environment, gitCommit, gitBranch, hostname, state.pendingMedia, closeModal],
  );

  return {
    state, openFeedbackMode, closeFeedbackMode, openModal, closeModal,
    addMedia, removeMedia, clearMedia, submitFeedback,
  };
}
