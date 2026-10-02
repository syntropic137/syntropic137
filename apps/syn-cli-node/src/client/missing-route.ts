/**
 * A 404 that means "this server has no such route", explained (#1501 B).
 *
 * WHY: the CLI and the server ship separately, and two builds on the same
 * release line can still differ by a feature. `syn execution sessions` against
 * a 0.33 beta that predates session inventory printed
 * `Failed to read session inventory: Not Found`, which reads as "no such
 * execution" and names neither the server nor its version.
 *
 * Every request through the typed client is to a path in the generated spec,
 * so every one is a route this CLI knows. When the server answers one with the
 * router's own 404 body, the route is missing on the server, and the body is
 * replaced with a sentence saying so and naming the build that answered. The
 * status stays 404, so callers that branch on it behave as before; `unwrap`
 * and anything else reading `detail` simply get a true one.
 */

import type { Middleware } from "openapi-fetch";
import { describeMissingRoute } from "../output/build.js";
import type { ServerBuild } from "./server-build.js";

/** What FastAPI (Starlette) answers when no route matches. Every handler 404
 * in syn-api carries its own detail, so this one body means the route itself. */
const ROUTE_MISS_DETAIL = "Not Found";

/** The route the probe itself asks. Explaining its 404 would await the probe
 * from inside the probe; and a missing /version is already its own verdict
 * (`no-version-route`), never a mismatch (#1494). */
const VERSION_ROUTE = "/version";

/**
 * `serverBuild` is the same memoised probe the preflight awaited, so by the
 * time a command's request 404s the answer is already in hand and no second
 * /version request is made.
 */
export function explainMissingRoutes(
  serverBuild: () => Promise<ServerBuild>,
  deployment: string,
): Middleware {
  return {
    async onResponse({ request, response, schemaPath }) {
      if (response.status !== 404 || schemaPath === VERSION_ROUTE) return undefined;
      if (!(await isRouteMiss(response))) return undefined;
      const detail = describeMissingRoute(await serverBuild(), deployment, `${request.method} ${schemaPath}`);
      return new Response(JSON.stringify({ detail }), {
        status: 404,
        statusText: response.statusText,
        headers: { "Content-Type": "application/json" },
      });
    },
  };
}

async function isRouteMiss(response: Response): Promise<boolean> {
  try {
    const body: unknown = await response.clone().json();
    return typeof body === "object" && body !== null && "detail" in body && body.detail === ROUTE_MISS_DETAIL;
  } catch {
    return false;
  }
}
