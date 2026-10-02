/**
 * Which server build is this CLI talking to, and is it the same release line?
 *
 * The one place that knows about `GET /version`, how each side spells a
 * release, and what counts as skew (#1473). Callers get a verdict, never a
 * version string to compare themselves.
 *
 * WHY it exists: the CLI ships to npm and the server is deployed separately, so
 * they drift. When they did, a 0.29.0 CLI against a 0.33 server printed
 * `No workflow found matching: ...` and nothing pointed at the version gap.
 */

import { DEV_CLI_VERSION, VERSION_PROBE_TIMEOUT_MS } from "../config.js";
import type { components } from "../generated/api-types.js";
import { api } from "./typed.js";

export type BuildInfo = components["schemas"]["BuildInfo"];

/** What asking the server produced. Always returned, never thrown. */
export type ServerBuild =
  | { kind: "reported"; build: BuildInfo }
  /** 404: a release older than the route, or a URL that is not syn-api. */
  | { kind: "no-version-route" }
  /** Network error, timeout, a body that is not JSON, any other non-2xx. */
  | { kind: "unanswered"; reason: string };

export type ReleaseSkew =
  | { kind: "match" }
  | { kind: "mismatch"; cli: string; server: string; cliLine: string; serverLine: string }
  /** Nothing proves the lines differ: a dev CLI, a server that could not read
   * its own release, a 404, an unreachable server, or a version neither side
   * can parse. Silence is the right answer for every one of these. */
  | { kind: "undetermined" };

/**
 * Ask the server which build it is. Bounded by VERSION_PROBE_TIMEOUT_MS,
 * because this runs before every API command and a host that drops packets
 * would otherwise hold the command for the full connect timeout.
 *
 * Total by construction: every I/O step is inside the one `try`, so a probe
 * bug can at worst make the answer `unanswered`, never fail the command.
 */
export async function probeServerBuild(): Promise<ServerBuild> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), VERSION_PROBE_TIMEOUT_MS);
  try {
    const { data, response } = await api.GET("/version", { signal: controller.signal });
    if (response.status === 404) return { kind: "no-version-route" };
    if (!response.ok || data === undefined) {
      return { kind: "unanswered", reason: `HTTP ${response.status}` };
    }
    // openapi-fetch does no runtime validation, so a 200 whose JSON root is
    // `null`, a string or an array arrives typed as BuildInfo. Only an object
    // can be one; anything else would crash the first `build.version` read,
    // outside this `try`, and take the command down with it.
    if (typeof data !== "object" || data === null || Array.isArray(data)) {
      return { kind: "unanswered", reason: "response body is not a build object" };
    }
    return { kind: "reported", build: data };
  } catch (err) {
    const reason = controller.signal.aborted
      ? `no answer within ${VERSION_PROBE_TIMEOUT_MS}ms`
      : err instanceof Error ? err.message : String(err);
    return { kind: "unanswered", reason };
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Compare release lines (major.minor). Patch and pre-release are ignored: the
 * two sides spell betas differently (npm `0.33.0-beta.1`, PEP 440 `0.33.0b5`),
 * so anything finer would warn on every beta.
 *
 * Only a comparison of two parsed versions can produce `mismatch`. A 404 on
 * /version is NOT one: the server may be the same release line and merely
 * older than the route, or the URL may not be syn-api at all.
 */
export function compareReleases(cliVersion: string, server: ServerBuild): ReleaseSkew {
  if (server.kind !== "reported" || cliVersion === DEV_CLI_VERSION) {
    return { kind: "undetermined" };
  }
  // Read defensively: openapi-fetch does no runtime validation, so `version`
  // is whatever the body held, whatever the schema says.
  const serverVersion: unknown = server.build.version;
  if (typeof serverVersion !== "string") return { kind: "undetermined" };

  const cliLine = releaseLine(cliVersion);
  const serverLine = releaseLine(serverVersion);
  if (cliLine === undefined || serverLine === undefined) return { kind: "undetermined" };
  if (cliLine === serverLine) return { kind: "match" };
  return { kind: "mismatch", cli: cliVersion, server: serverVersion, cliLine, serverLine };
}

/** `0.33.0-beta.1`, `0.33.0b5`, `v0.33.2` -> `0.33`. Numbers, not prefixes, so
 * `0.3.30` and `0.33.0` are different lines. */
function releaseLine(version: string): string | undefined {
  const match = /^v?(\d+)\.(\d+)(?:[.+\-a-z]|$)/i.exec(version.trim());
  if (!match) return undefined;
  return `${Number(match[1])}.${Number(match[2])}`;
}
