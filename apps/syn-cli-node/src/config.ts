import { DEFAULT_SELFHOST_API_URL, ENV_SYN_API_URL } from "./constants.js";

export const CLI_NAME = "syn";
export const CLI_DESCRIPTION =
  "Syntropic137 - Event-sourced workflow engine for AI agents";

declare const __CLI_VERSION__: string;
/** What an unbuilt CLI (vitest, tsx) calls itself. It names no release. */
export const DEV_CLI_VERSION = "0.0.0-dev";
export const CLI_VERSION =
  typeof __CLI_VERSION__ !== "undefined" ? __CLI_VERSION__ : DEV_CLI_VERSION;

export const DEFAULT_TIMEOUT_MS = 30_000;
/** The release-skew probe runs in front of every API command, so a host that
 * drops packets must cost seconds, not the platform's connect timeout. */
export const VERSION_PROBE_TIMEOUT_MS = 2_000;
export const SSE_CONNECT_TIMEOUT_MS = 5_000;

export function getApiUrl(): string {
  const url = process.env[ENV_SYN_API_URL] ?? DEFAULT_SELFHOST_API_URL;
  // Strip /api/v1 suffix if present - the HTTP client adds it automatically.
  return url.replace(/\/api\/v1\/*$/, "");
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
