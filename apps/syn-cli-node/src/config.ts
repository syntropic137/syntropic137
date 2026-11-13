import { DEFAULT_SELFHOST_API_URL, ENV_SYN_API_URL } from "./constants.js";

export const CLI_NAME = "syn";
export const CLI_DESCRIPTION =
  "Syntropic137 - Event-sourced workflow engine for AI agents";

declare const __CLI_VERSION__: string;
/** What an unbuilt CLI (vitest, tsx) reports. It names no release, so nothing
 * is compared against it. */
export const DEV_CLI_VERSION = "0.0.0-dev";
export const CLI_VERSION =
  typeof __CLI_VERSION__ !== "undefined" ? __CLI_VERSION__ : DEV_CLI_VERSION;

export const DEFAULT_TIMEOUT_MS = 30_000;
/** Bound on the `GET /version` probe that runs before every API command. */
export const VERSION_PROBE_TIMEOUT_MS = 2_000;
export const SSE_CONNECT_TIMEOUT_MS = 5_000;

export function getApiUrl(): string {
  const url = process.env[ENV_SYN_API_URL] ?? DEFAULT_SELFHOST_API_URL;
  // Strip /api/v1 suffix if present - the HTTP client adds it automatically.
  return url.replace(/\/api\/v1\/*$/, "");
}

/** The credentials this CLI sends, as read from the environment. */
export type Credentials =
  | { kind: "bearer"; token: string }
  | { kind: "basic"; user: string; password: string }
  /** `user` is set when SYN_API_USER is but SYN_API_PASSWORD is not, which
   * sends nothing and is worth saying so. */
  | { kind: "none"; user?: string };

/**
 * Read credentials from environment.
 *
 * Supports:
 *   - Bearer token: SYN_API_TOKEN (wins when set)
 *   - Basic auth:   SYN_API_USER + SYN_API_PASSWORD
 */
export function getCredentials(): Credentials {
  const token = process.env["SYN_API_TOKEN"];
  if (token) return { kind: "bearer", token };

  const user = process.env["SYN_API_USER"];
  const password = process.env["SYN_API_PASSWORD"];
  if (user && password) return { kind: "basic", user, password };
  return user ? { kind: "none", user } : { kind: "none" };
}

/**
 * Build auth headers from environment.
 *
 * Returns an empty object when no credentials are configured (localhost use).
 */
export function getAuthHeaders(credentials: Credentials = getCredentials()): Record<string, string> {
  switch (credentials.kind) {
    case "bearer":
      return { Authorization: `Bearer ${credentials.token}` };
    case "basic": {
      const encoded = Buffer.from(`${credentials.user}:${credentials.password}`).toString("base64");
      return { Authorization: `Basic ${encoded}` };
    }
    case "none":
      return {};
  }
}

/** What was sent, in words, for an error message. Names the user, never a
 * password or token. */
export function describeCredentials(credentials: Credentials): string {
  switch (credentials.kind) {
    case "bearer":
      return "a bearer token from SYN_API_TOKEN";
    case "basic":
      return `Basic auth as user ${JSON.stringify(credentials.user)}`;
    case "none":
      return credentials.user === undefined
        ? "no credentials"
        : `no credentials (SYN_API_USER is ${JSON.stringify(credentials.user)} but SYN_API_PASSWORD is not set)`;
  }
}
