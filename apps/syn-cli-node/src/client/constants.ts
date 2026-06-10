/**
 * Shared constants for HTTP clients.
 *
 * Keep this file tiny - it exists purely to avoid drift between
 * typed.ts, sse.ts, and yaml-upload.ts.
 */

/**
 * Prefix prepended to API paths. Production (selfhost) and dev (`just dev`)
 * both front the API with nginx that strips this prefix, so the CLI always
 * sends it. The previous `SYN_NO_PREFIX=1` escape hatch was removed once
 * the dev gateway closed the parity gap (#762).
 */
export const API_PREFIX = "/api/v1";
