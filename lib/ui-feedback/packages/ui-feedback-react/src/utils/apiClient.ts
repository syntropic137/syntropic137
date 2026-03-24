/**
 * API client utilities for the feedback API
 */

export class ApiError extends Error {
  status: number;
  body?: unknown;

  constructor(message: string, status: number, body?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
  }
}

export class NetworkError extends Error {
  readonly originalError?: Error;

  constructor(message: string, originalError?: Error) {
    super(message);
    this.name = 'NetworkError';
    this.originalError = originalError;
  }
}

function classifyNetworkError(message: string, originalError?: Error): NetworkError {
  if (message.includes('Failed to fetch') || message.includes('NetworkError')) {
    return new NetworkError('Feedback API unavailable. Run: just feedback-backend', originalError);
  }
  if (message.includes('CORS') || message.includes('cross-origin')) {
    return new NetworkError('CORS error: Feedback API may need CORS configuration', originalError);
  }
  return new NetworkError(`Network error: ${message}`, originalError);
}

/**
 * Wrapper for fetch that provides better error messages for network failures.
 */
export async function safeFetch(url: string, options?: RequestInit): Promise<Response> {
  try {
    return await fetch(url, options);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    const originalError = err instanceof Error ? err : undefined;
    throw classifyNetworkError(message, originalError);
  }
}

function getErrorMessage(status: number, statusText: string): string {
  if (status === 404) return 'Feedback endpoint not found. Check API URL configuration.';
  if (status === 500) return 'Server error. Check feedback API logs.';
  if (status === 422) return 'Invalid data. Please check your input.';
  return `API error: ${status} ${statusText}`;
}

export async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      body = await response.text();
    }
    throw new ApiError(getErrorMessage(response.status, response.statusText), response.status, body);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json();
}
