export const CLI_NAME = "syn";
export const CLI_DESCRIPTION =
  "Syntropic137 - Event-sourced workflow engine for AI agents";

declare const __CLI_VERSION__: string;
export const CLI_VERSION =
  typeof __CLI_VERSION__ !== "undefined" ? __CLI_VERSION__ : "0.0.0-dev";

export const DEFAULT_TIMEOUT_MS = 30_000;
export const SSE_CONNECT_TIMEOUT_MS = 5_000;

export function getApiUrl(): string {
  return process.env["SYN_API_URL"] ?? "http://localhost:8137";
}

/**
 * Build auth headers from environment.
 *
 * Supports:
 *   - Bearer token: SYN_API_TOKEN
 *   - Basic auth:   SYN_API_USER + SYN_API_PASSWORD
 *
 * Returns an empty object when no credentials are configured (localhost use).
 */
export function getAuthHeaders(): Record<string, string> {
  const token = process.env["SYN_API_TOKEN"];
  if (token) return { Authorization: `Bearer ${token}` };

  const user = process.env["SYN_API_USER"];
  const password = process.env["SYN_API_PASSWORD"];
  if (user && password) {
    const encoded = Buffer.from(`${user}:${password}`).toString("base64");
    return { Authorization: `Basic ${encoded}` };
  }

  return {};
}
