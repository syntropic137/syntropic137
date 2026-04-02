import { DEFAULT_TIMEOUT_MS, SSE_CONNECT_TIMEOUT_MS, getApiUrl, getAuthHeaders } from "../config.js";

export interface ApiResponse<T> {
  status: number;
  data: T;
}

export interface SynClientOptions {
  baseUrl?: string;
  timeoutMs?: number;
}

export class SynClient {
  private readonly baseUrl: string;
  private readonly timeoutMs: number;
  private readonly authHeaders: Record<string, string>;

  constructor(options?: SynClientOptions) {
    this.baseUrl = options?.baseUrl ?? getApiUrl();
    this.timeoutMs = options?.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    this.authHeaders = getAuthHeaders();
  }

  async get<T>(
    path: string,
    params?: Record<string, string | number | boolean | undefined>,
  ): Promise<ApiResponse<T>> {
    const url = this.buildUrl(path, params);
    return this.request<T>(url, { method: "GET" });
  }

  async post<T>(
    path: string,
    body?: Record<string, unknown>,
    params?: Record<string, string>,
  ): Promise<ApiResponse<T>> {
    const url = this.buildUrl(path, params);
    return this.request<T>(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    });
  }

  async put<T>(
    path: string,
    body?: Record<string, unknown>,
  ): Promise<ApiResponse<T>> {
    const url = this.buildUrl(path);
    return this.request<T>(url, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    });
  }

  async patch<T>(
    path: string,
    body?: Record<string, unknown>,
  ): Promise<ApiResponse<T>> {
    const url = this.buildUrl(path);
    return this.request<T>(url, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    });
  }

  async delete<T>(path: string): Promise<ApiResponse<T>> {
    const url = this.buildUrl(path);
    return this.request<T>(url, { method: "DELETE" });
  }

  async stream(path: string): Promise<ReadableStream<Uint8Array>> {
    const url = this.buildUrl(path);
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), SSE_CONNECT_TIMEOUT_MS);

    const response = await fetch(url.toString(), {
      method: "GET",
      headers: { ...this.authHeaders },
      signal: controller.signal,
    });

    clearTimeout(timer);

    if (!response.body) {
      throw new Error("Response body is null");
    }

    return response.body;
  }

  private buildUrl(
    path: string,
    params?: Record<string, string | number | boolean | undefined>,
  ): URL {
    // Concatenate base path with request path so that a base URL like
    // "http://host:8137/api/v1" + "/health" → "http://host:8137/api/v1/health"
    // (plain `new URL(path, base)` would discard the base path component).
    const base = new URL(this.baseUrl);
    const basePath = base.pathname.replace(/\/+$/, "");
    const reqPath = path.startsWith("/") ? path : `/${path}`;
    const url = new URL(`${basePath}${reqPath}`, base);
    if (params) {
      for (const [key, value] of Object.entries(params)) {
        if (value !== undefined) {
          url.searchParams.set(key, String(value));
        }
      }
    }
    return url;
  }

  private async request<T>(url: URL, init: RequestInit): Promise<ApiResponse<T>> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);

    try {
      const existingHeaders = init.headers as Record<string, string> | undefined;
      const response = await fetch(url.toString(), {
        ...init,
        headers: { ...this.authHeaders, ...existingHeaders },
        signal: controller.signal,
      });
      const data = response.status === 204 || response.status === 205
        ? (undefined as T)
        : (await response.json()) as T;
      return { status: response.status, data };
    } finally {
      clearTimeout(timer);
    }
  }
}
