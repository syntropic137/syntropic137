/**
 * Shared constants for HTTP clients.
 *
 * Keep this file tiny — it exists purely to avoid drift between
 * typed.ts, sse.ts, and yaml-upload.ts.
 */

/**
 * Prefix prepended to API paths. Set SYN_NO_PREFIX=1 when the configured
 * base URL already ends in /api/v1 (e.g. talking to an internal service
 * that mounts routes directly).
 */
export const API_PREFIX =
  process.env["SYN_NO_PREFIX"] === "1" || process.env["SYN_NO_PREFIX"] === "true"
    ? ""
    : "/api/v1";
