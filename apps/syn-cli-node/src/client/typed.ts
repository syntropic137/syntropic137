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
import { getApiUrl, getAuthHeaders } from "../config.js";

const API_PREFIX = "/api/v1";

export function createTypedClient() {
  const baseUrl = getApiUrl().replace(/\/+$/, "");
  return createClient<paths>({
    baseUrl: `${baseUrl}${API_PREFIX}`,
    headers: getAuthHeaders(),
  });
}

/** Singleton typed client — use this in command handlers. */
export const api = createTypedClient();
