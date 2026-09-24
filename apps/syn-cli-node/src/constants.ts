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

/**
 * `cost_by_model` bucket for cost whose model no harness reported (ADR-067 D9).
 * Mirrors `UNKNOWN_MODEL_KEY` in syn_shared.observed_model; the API never keys
 * cost by an alias, so this is the only non-id key a client will see.
 */
export const UNKNOWN_MODEL_KEY = "unattributed-model";

/** How an unreported model is shown. Mirrors `UNKNOWN_MODEL_DISPLAY`. */
export const UNKNOWN_MODEL_DISPLAY = "unknown";
