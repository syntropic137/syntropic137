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

import createClient from "openapi-fetch";
import type { paths } from "../generated/api-types.js";
import { CLIError } from "../framework/errors.js";
import { getApiUrl, getAuthHeaders } from "../config.js";

const API_PREFIX = (process.env["SYN_NO_PREFIX"] === "1" || process.env["SYN_NO_PREFIX"] === "true") ? "" : "/api/v1";

export function createTypedClient() {
  const baseUrl = getApiUrl().replace(/\/+$/, "");
  return createClient<paths>({
    baseUrl: `${baseUrl}${API_PREFIX}`,
    headers: getAuthHeaders(),
    // Resolve fetch at call time, not at client creation time.
    // This allows tests to stub globalThis.fetch after module import.
    fetch: (...args) => globalThis.fetch(...args),
  });
}

/** Singleton typed client — use this in command handlers. */
export const api = createTypedClient();

/** Extract data from a typed API response, throwing CLIError on failure.
 *  Handles 204 No Content (data=undefined, error=undefined) gracefully. */
export function unwrap<T>(result: { data?: T; error?: unknown }, context: string): T {
  if (result.error) {
    const detail = typeof result.error === "object" && result.error !== null && "detail" in result.error
      ? String((result.error as { detail: unknown }).detail)
      : String(result.error);
    throw new CLIError(`${context}: ${detail}`);
  }
  return result.data as T;
}
