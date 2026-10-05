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
 * How long a request may take, headers and body together, before it fails.
 * Without a bound a stalled response leaves its caller waiting forever, and a
 * caller that shows a spinner shows it forever (the "Loading feedback..." bug).
 */
export const REQUEST_TIMEOUT_MS = 15_000;

function getErrorMessage(status: number, statusText: string): string {
  if (status === 404) return 'Feedback endpoint not found. Check API URL configuration.';
  if (status === 500) return 'Server error. Check feedback API logs.';
  if (status === 422) return 'Invalid data. Please check your input.';
  return `API error: ${status} ${statusText}`;
}

async function handleResponse<T>(response: Response): Promise<T> {
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

/**
 * Fetch `url` and parse the response, failing with a NetworkError if the whole
 * exchange, body included, has not finished within `timeoutMs`.
 */
export async function request<T>(url: string, options?: RequestInit, timeoutMs = REQUEST_TIMEOUT_MS): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { ...options, signal: controller.signal });
    return await handleResponse<T>(response);
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if (controller.signal.aborted) {
      throw new NetworkError(`Feedback API did not respond within ${timeoutMs / 1000}s`, err instanceof Error ? err : undefined);
    }
    const message = err instanceof Error ? err.message : 'Unknown error';
    throw classifyNetworkError(message, err instanceof Error ? err : undefined);
  } finally {
    clearTimeout(timer);
  }
}
