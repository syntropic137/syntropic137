/**
 * Type-safe API client powered by openapi-fetch.
 *
 * Usage:
 *   import { api } from "../client/typed.js";
 *   const { data, error } = await api.GET("/triggers", { params: { query: { status: "active" } } });
 *   // data is fully typed from the OpenAPI spec — no Record<string, unknown>
 *
 * Migrate commands incrementally: replace apiGet/apiGetPaginated calls with api.GET/api.POST.
 */

import createClient, { type Client } from "openapi-fetch";
import type { paths } from "../generated/api-types.js";
import { CLIError } from "../framework/errors.js";
import { getApiUrl, getAuthHeaders } from "../config.js";
import { API_PREFIX } from "./constants.js";

/**
 * A typed API client that knows, and can be asked, which deployment it sends to.
 */
export interface TypedClient extends Client<paths> {
  /**
   * The deployment this client talks to: its resolved base URL, without the
   * `/api/v1` prefix.
   *
   * WHY it hangs off the client rather than being resolved again at the point
   * of use: a command that reports where it started work has to report where
   * the request actually went. The requests below are built from this exact
   * string, so the two cannot disagree — whereas re-reading the environment
   * later can, and a report that can disagree with the request is the bug
   * (issue #1264).
   */
  readonly deployment: string;
}

export function createTypedClient(): TypedClient {
  const deployment = getApiUrl().replace(/\/+$/, "");
  const client = createClient<paths>({
    baseUrl: `${deployment}${API_PREFIX}`,
    headers: getAuthHeaders(),
    // Resolve fetch at call time, not at client creation time.
    // This allows tests to stub globalThis.fetch after module import.
    fetch: (...args) => globalThis.fetch(...args),
  });
  return Object.assign(client, { deployment });
}

/** Singleton typed client — use this in command handlers. */
export const api: TypedClient = createTypedClient();

/** Extract data from a typed API response, throwing CLIError on failure.
 *
 *  Handles 204 No Content (data=undefined, error=undefined) gracefully.
 *
 *  WHY `response.ok` is checked and not just `error`: openapi-fetch represents
 *  an EMPTY error body as `{error: undefined}`, so a 500 with no body used to
 *  slip through here and be returned as data. Callers then printed success and
 *  crashed later reading a field off undefined, reporting an unrelated
 *  TypeError instead of the actual server failure.
 */
export function unwrap<T>(
  result: { data?: T; error?: unknown; response?: Response },
  context: string,
): T {
  if (result.response && !result.response.ok && !result.error) {
    throw new CLIError(
      `${context}: request failed with ${result.response.status} ${result.response.statusText}`.trim(),
    );
  }
  if (result.error) {
    const detail = typeof result.error === "object" && result.error !== null && "detail" in result.error
      ? String((result.error as { detail: unknown }).detail)
      : String(result.error);
    throw new CLIError(`${context}: ${detail}`);
  }
  return result.data as T;
}
