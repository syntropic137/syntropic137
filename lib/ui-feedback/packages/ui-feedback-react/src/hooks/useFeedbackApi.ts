/**
 * Hook for interacting with the UI Feedback API
 */

import { useCallback, useMemo } from 'react';
import type {
  FeedbackCreate,
  FeedbackItem,
  FeedbackItemWithMedia,
  FeedbackList,
  FeedbackStats,
  FeedbackUpdate,
  MediaUpload,
} from '../types';
import { handleResponse, safeFetch } from '../utils/apiClient';

export interface UseFeedbackApiOptions {
  apiUrl: string;
}

export interface FeedbackApiResult {
  createFeedback: (data: FeedbackCreate) => Promise<FeedbackItem>;
  getFeedback: (id: string) => Promise<FeedbackItemWithMedia>;
  listFeedback: (params?: ListFeedbackParams) => Promise<FeedbackList>;
  updateFeedback: (id: string, data: FeedbackUpdate) => Promise<FeedbackItem>;
  deleteFeedback: (id: string) => Promise<void>;
  uploadMedia: (feedbackId: string, media: MediaUpload) => Promise<void>;
  getMediaUrl: (feedbackId: string, mediaId: string) => string;
  deleteMedia: (feedbackId: string, mediaId: string) => Promise<void>;
  getStats: (appName?: string) => Promise<FeedbackStats>;
}

export interface ListFeedbackParams {
  status?: string;
  type?: string;
  priority?: string;
  app?: string;
  search?: string;
  page?: number;
  limit?: number;
  orderBy?: string;
  desc?: boolean;
}

function buildListUrl(baseUrl: string, params: ListFeedbackParams): string {
  const sp = new URLSearchParams();
  if (params.status) sp.set('status', params.status);
  if (params.type) sp.set('type', params.type);
  if (params.priority) sp.set('priority', params.priority);
  if (params.app) sp.set('app', params.app);
  if (params.search) sp.set('search', params.search);
  if (params.page) sp.set('page', params.page.toString());
  if (params.limit) sp.set('limit', params.limit.toString());
  if (params.orderBy) sp.set('order_by', params.orderBy);
  if (params.desc !== undefined) sp.set('desc', params.desc.toString());
  const qs = sp.toString();
  return qs ? `${baseUrl}/feedback?${qs}` : `${baseUrl}/feedback`;
}

export function useFeedbackApi({ apiUrl }: UseFeedbackApiOptions): FeedbackApiResult {
  const baseUrl = apiUrl.replace(/\/$/, '');

  const createFeedback = useCallback(
    async (data: FeedbackCreate) => {
      const response = await safeFetch(`${baseUrl}/feedback`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
      });
      return handleResponse<FeedbackItem>(response);
    },
    [baseUrl],
  );

  const getFeedback = useCallback(
    async (id: string) => {
      const response = await safeFetch(`${baseUrl}/feedback/${id}`);
      return handleResponse<FeedbackItemWithMedia>(response);
    },
    [baseUrl],
  );

  const listFeedback = useCallback(
    async (params: ListFeedbackParams = {}) => {
      const response = await safeFetch(buildListUrl(baseUrl, params));
      return handleResponse<FeedbackList>(response);
    },
    [baseUrl],
  );

  const updateFeedback = useCallback(
    async (id: string, data: FeedbackUpdate) => {
      const response = await safeFetch(`${baseUrl}/feedback/${id}`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
      });
      return handleResponse<FeedbackItem>(response);
    },
    [baseUrl],
  );

  const deleteFeedback = useCallback(
    async (id: string) => {
      const response = await safeFetch(`${baseUrl}/feedback/${id}`, { method: 'DELETE' });
      await handleResponse<void>(response);
    },
    [baseUrl],
  );

  const uploadMedia = useCallback(
    async (feedbackId: string, media: MediaUpload) => {
      const formData = new FormData();
      formData.append('file', media.blob, media.fileName || 'file');
      formData.append('media_type', media.mediaType);
      const response = await safeFetch(`${baseUrl}/feedback/${feedbackId}/media`, { method: 'POST', body: formData });
      await handleResponse<void>(response);
    },
    [baseUrl],
  );

  const getMediaUrl = useCallback(
    (feedbackId: string, mediaId: string) => `${baseUrl}/feedback/${feedbackId}/media/${mediaId}`,
    [baseUrl],
  );

  const deleteMedia = useCallback(
    async (feedbackId: string, mediaId: string) => {
      const response = await safeFetch(`${baseUrl}/feedback/${feedbackId}/media/${mediaId}`, { method: 'DELETE' });
      await handleResponse<void>(response);
    },
    [baseUrl],
  );

  const getStats = useCallback(
    async (appName?: string) => {
      const url = appName ? `${baseUrl}/feedback/stats?app=${encodeURIComponent(appName)}` : `${baseUrl}/feedback/stats`;
      const response = await safeFetch(url);
      return handleResponse<FeedbackStats>(response);
    },
    [baseUrl],
  );

  return useMemo(
    () => ({ createFeedback, getFeedback, listFeedback, updateFeedback, deleteFeedback, uploadMedia, getMediaUrl, deleteMedia, getStats }),
    [createFeedback, getFeedback, listFeedback, updateFeedback, deleteFeedback, uploadMedia, getMediaUrl, deleteMedia, getStats],
  );
}
