/**
 * A 401, explained (#1571).
 *
 * WHY: through the selfhost gateway a failed Basic auth came back as nginx's
 * HTML 401 page, and the CLI printed that page (or "fetch failed"), naming
 * neither the deployment, the user it sent, nor where either came from. A
 * wrong username and a rotated password looked the same and took several
 * probes each to tell apart.
 *
 * Whatever the body - the gateway's JSON, an older gateway's HTML, syn-api's
 * own detail - a 401 means the credentials were refused, so the message says
 * where the request went, what was sent, and where to look. It never contains
 * a password or token: only the username, which the operator chose and the
 * server already saw.
 */

import type { Middleware } from "openapi-fetch";
import { describeCredentials, type Credentials } from "../config.js";

/** The sentence for a 401 from `deployment` to a request carrying `credentials`. */
export function describeUnauthorized(deployment: string, credentials: Credentials): string {
  return (
    `${deployment} answered 401 Unauthorized to ${describeCredentials(credentials)}. ` +
    "Credentials come from SYN_API_TOKEN (bearer) or SYN_API_USER + SYN_API_PASSWORD (Basic); " +
    "run `syn config show` to see what this CLI is sending."
  );
}

/**
 * Replace a 401's body with `{detail}` saying so. The status stays 401, so
 * callers that branch on it behave as before; `unwrap` and anything else
 * reading `detail` get the explanation instead of the server's page.
 *
 * `credentials` are the ones the client's headers were built from, so the
 * message names what was actually sent rather than re-reading the environment.
 */
export function explainUnauthorized(deployment: string, credentials: Credentials): Middleware {
  return {
    onResponse({ response }) {
      if (response.status !== 401) return undefined;
      return new Response(JSON.stringify({ detail: describeUnauthorized(deployment, credentials) }), {
        status: 401,
        statusText: response.statusText,
        headers: { "Content-Type": "application/json" },
      });
    },
  };
}
