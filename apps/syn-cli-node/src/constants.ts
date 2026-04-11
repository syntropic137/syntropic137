/**
 * Single source of truth for CLI port/URL constants.
 *
 * The CLI targets selfhost users - it connects to the nginx gateway
 * on port 8137, not the dev API on port 9137.
 *
 * See ADR-004: Environment Configuration with Pydantic Settings.
 */

export const SELFHOST_GATEWAY_PORT = 8137;
export const DEFAULT_SELFHOST_API_URL = `http://localhost:${SELFHOST_GATEWAY_PORT}`;
export const ENV_SYN_API_URL = "SYN_API_URL";
