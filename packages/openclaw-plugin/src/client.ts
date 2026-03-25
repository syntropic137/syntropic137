import { ApiError } from "./errors.js";

/** Discriminated union for API call results. */
export type ApiResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: ApiError };

export interface SyntropicClientConfig {
  apiUrl: string;
  apiKey?: string;
}

/**
 * Typed fetch() wrapper for the Syntropic137 HTTP API.
 *
 * All methods return `ApiResult<T>` — errors are values, never thrown.
 */
export class SyntropicClient {
  private readonly baseUrl: string;
  private readonly headers: Record<string, string>;

  constructor(config: SyntropicClientConfig) {
    // Strip trailing slash
    this.baseUrl = config.apiUrl.replace(/\/+$/, "");
    this.headers = { "Content-Type": "application/json" };
    if (config.apiKey) {
      this.headers["Authorization"] = `Bearer ${config.apiKey}`;
    }
  }

  /** Typed GET request. */
  async get<T>(path: string, params?: Record<string, string>): Promise<ApiResult<T>> {
    const url = this.buildUrl(path, params);
    return this.request<T>(url, { method: "GET" });
  }

  /** Typed POST request. */
  async post<T>(path: string, body?: unknown): Promise<ApiResult<T>> {
    const url = this.buildUrl(path);
    return this.request<T>(url, {
      method: "POST",
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  }

  private buildUrl(path: string, params?: Record<string, string>): string {
    const url = new URL(`${this.baseUrl}${path}`);
    if (params) {
      for (const [key, value] of Object.entries(params)) {
        if (value !== undefined && value !== "") {
          url.searchParams.set(key, value);
        }
      }
    }
    return url.toString();
  }

  private static parseErrorMessage(status: number, statusText: string, body: string): string {
    const fallback = `${status} ${statusText}`;
    if (!body) return fallback;
    try {
      const json = JSON.parse(body) as { detail?: string };
      return json.detail || fallback;
    } catch {
      return body;
    }
  }

  private async request<T>(url: string, init: RequestInit): Promise<ApiResult<T>> {
    try {
      const response = await fetch(url, {
        ...init,
        headers: this.headers,
      });

      if (!response.ok) {
        const text = await response.text().catch(() => "");
        const message = SyntropicClient.parseErrorMessage(response.status, response.statusText, text);
        return { ok: false, error: new ApiError(response.status, message) };
      }

      const data = (await response.json()) as T;
      return { ok: true, data };
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      return { ok: false, error: new ApiError(0, `Connection failed: ${message}`) };
    }
  }
}

/** Resolve client config from plugin config + env vars + defaults. */
export function resolveConfig(pluginConfig?: Partial<SyntropicClientConfig>): SyntropicClientConfig {
  return {
    apiUrl:
      pluginConfig?.apiUrl ||
      process.env["SYNTROPIC_URL"] ||
      "http://localhost:8137",
    apiKey:
      pluginConfig?.apiKey ||
      process.env["SYNTROPIC_API_KEY"] ||
      undefined,
  };
}
