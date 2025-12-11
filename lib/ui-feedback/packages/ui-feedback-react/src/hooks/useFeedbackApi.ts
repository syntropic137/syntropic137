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

export interface UseFeedbackApiOptions {
  apiUrl: string;
}

export interface FeedbackApiResult {
  // Feedback operations
  createFeedback: (data: FeedbackCreate) => Promise<FeedbackItem>;
  getFeedback: (id: string) => Promise<FeedbackItemWithMedia>;
  listFeedback: (params?: ListFeedbackParams) => Promise<FeedbackList>;
  updateFeedback: (id: string, data: FeedbackUpdate) => Promise<FeedbackItem>;
  deleteFeedback: (id: string) => Promise<void>;

  // Media operations
  uploadMedia: (feedbackId: string, media: MediaUpload) => Promise<void>;
  getMediaUrl: (feedbackId: string, mediaId: string) => string;
  deleteMedia: (feedbackId: string, mediaId: string) => Promise<void>;

  // Stats
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

class ApiError extends Error {
  status: number;
  body?: unknown;

  constructor(message: string, status: number, body?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
  }
}

class NetworkError extends Error {
  constructor(message: string, public readonly originalError?: Error) {
    super(message);
    this.name = 'NetworkError';
  }
}

/**
 * Wrapper for fetch that provides better error messages for network failures.
 */
async function safeFetch(url: string, options?: RequestInit): Promise<Response> {
  try {
    return await fetch(url, options);
  } catch (err) {
    // Network errors (API not running, CORS, etc.)
    const message = err instanceof Error ? err.message : 'Unknown error';
    
    if (message.includes('Failed to fetch') || message.includes('NetworkError')) {
      throw new NetworkError(
        'Feedback API unavailable. Run: just feedback-backend',
        err instanceof Error ? err : undefined
      );
    }
    
    if (message.includes('CORS') || message.includes('cross-origin')) {
      throw new NetworkError(
        'CORS error: Feedback API may need CORS configuration',
        err instanceof Error ? err : undefined
      );
    }
    
    throw new NetworkError(
      `Network error: ${message}`,
      err instanceof Error ? err : undefined
    );
  }
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      body = await response.text();
    }
    
    // Provide helpful messages for common HTTP errors
    let message = `API error: ${response.status} ${response.statusText}`;
    if (response.status === 404) {
      message = 'Feedback endpoint not found. Check API URL configuration.';
    } else if (response.status === 500) {
      message = 'Server error. Check feedback API logs.';
    } else if (response.status === 422) {
      message = 'Invalid data. Please check your input.';
    }
    
    throw new ApiError(message, response.status, body);
  }

  // Handle 204 No Content
  if (response.status === 204) {
    return undefined as T;
  }

  return response.json();
}

export function useFeedbackApi({ apiUrl }: UseFeedbackApiOptions): FeedbackApiResult {
  const baseUrl = apiUrl.replace(/\/$/, ''); // Remove trailing slash

  const createFeedback = useCallback(
    async (data: FeedbackCreate): Promise<FeedbackItem> => {
      const response = await safeFetch(`${baseUrl}/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      return handleResponse<FeedbackItem>(response);
    },
    [baseUrl]
  );

  const getFeedback = useCallback(
    async (id: string): Promise<FeedbackItemWithMedia> => {
      const response = await safeFetch(`${baseUrl}/feedback/${id}`);
      return handleResponse<FeedbackItemWithMedia>(response);
    },
    [baseUrl]
  );

  const listFeedback = useCallback(
    async (params: ListFeedbackParams = {}): Promise<FeedbackList> => {
      const searchParams = new URLSearchParams();
      if (params.status) searchParams.set('status', params.status);
      if (params.type) searchParams.set('type', params.type);
      if (params.priority) searchParams.set('priority', params.priority);
      if (params.app) searchParams.set('app', params.app);
      if (params.search) searchParams.set('search', params.search);
      if (params.page) searchParams.set('page', params.page.toString());
      if (params.limit) searchParams.set('limit', params.limit.toString());
      if (params.orderBy) searchParams.set('order_by', params.orderBy);
      if (params.desc !== undefined) searchParams.set('desc', params.desc.toString());

      const url = `${baseUrl}/feedback${searchParams.toString() ? `?${searchParams}` : ''}`;
      const response = await safeFetch(url);
      return handleResponse<FeedbackList>(response);
    },
    [baseUrl]
  );

  const updateFeedback = useCallback(
    async (id: string, data: FeedbackUpdate): Promise<FeedbackItem> => {
      const response = await safeFetch(`${baseUrl}/feedback/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      return handleResponse<FeedbackItem>(response);
    },
    [baseUrl]
  );

  const deleteFeedback = useCallback(
    async (id: string): Promise<void> => {
      const response = await safeFetch(`${baseUrl}/feedback/${id}`, {
        method: 'DELETE',
      });
      await handleResponse<void>(response);
    },
    [baseUrl]
  );

  const uploadMedia = useCallback(
    async (feedbackId: string, media: MediaUpload): Promise<void> => {
      const formData = new FormData();
      formData.append('file', media.blob, media.fileName || 'file');
      formData.append('media_type', media.mediaType);

      const response = await safeFetch(`${baseUrl}/feedback/${feedbackId}/media`, {
        method: 'POST',
        body: formData,
      });
      await handleResponse<void>(response);
    },
    [baseUrl]
  );

  const getMediaUrl = useCallback(
    (feedbackId: string, mediaId: string): string => {
      return `${baseUrl}/feedback/${feedbackId}/media/${mediaId}`;
    },
    [baseUrl]
  );

  const deleteMedia = useCallback(
    async (feedbackId: string, mediaId: string): Promise<void> => {
      const response = await safeFetch(`${baseUrl}/feedback/${feedbackId}/media/${mediaId}`, {
        method: 'DELETE',
      });
      await handleResponse<void>(response);
    },
    [baseUrl]
  );

  const getStats = useCallback(
    async (appName?: string): Promise<FeedbackStats> => {
      const url = appName
        ? `${baseUrl}/feedback/stats?app=${encodeURIComponent(appName)}`
        : `${baseUrl}/feedback/stats`;
      const response = await safeFetch(url);
      return handleResponse<FeedbackStats>(response);
    },
    [baseUrl]
  );

  // Memoize the return object to prevent infinite re-render loops
  // when consumers use the api object in useCallback/useEffect dependencies
  return useMemo(
    () => ({
      createFeedback,
      getFeedback,
      listFeedback,
      updateFeedback,
      deleteFeedback,
      uploadMedia,
      getMediaUrl,
      deleteMedia,
      getStats,
    }),
    [
      createFeedback,
      getFeedback,
      listFeedback,
      updateFeedback,
      deleteFeedback,
      uploadMedia,
      getMediaUrl,
      deleteMedia,
      getStats,
    ]
  );
}
