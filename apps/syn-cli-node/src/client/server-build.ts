/**
 * Which syn-api build is on the other end, and is it the same release as us?
 *
 * The CLI ships to npm and the server is deployed separately, so they drift.
 * When they do, commands fail with errors that read like data problems — a
 * 0.29 CLI against a 0.33 server printed "No workflow found matching: …" and
 * nothing pointed at the version skew (#1473). This module is the one place
 * that knows how to ask the server and how to compare the answer.
 */

import { DEV_CLI_VERSION, VERSION_PROBE_TIMEOUT_MS } from "../config.js";
import type { components } from "../generated/api-types.js";
import { api } from "./typed.js";

export type BuildInfo = components["schemas"]["BuildInfo"];

/** What asking the server produced. Always returned, never thrown: a probe
 * that can throw is a probe that can stop the command it runs in front of. */
export type ServerBuild =
  | { kind: "reported"; build: BuildInfo }
  | { kind: "unanswered"; reason: string };

export type Skew =
  | { kind: "match" }
  | { kind: "mismatch"; cli: string; server: string }
  /** Nothing proves the releases differ: a dev CLI, a server that could not
   * read its own release, or a version neither side can parse. */
  | { kind: "undetermined" };

/** Ask the server which build it is, bounded by VERSION_PROBE_TIMEOUT_MS.
 *
 * A 404 is `unanswered`, not evidence of an old server: `/version` arrived
 * after `/health`, so a server on our own release line can lack it, and so can
 * a URL that is not syn-api at all. Neither tells us the releases differ. */
export async function probeServerBuild(): Promise<ServerBuild> {
  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(), VERSION_PROBE_TIMEOUT_MS);
  try {
    const { data, response } = await api.GET("/version", { signal: abort.signal });
    if (response.status === 404) {
      return {
        kind: "unanswered",
        reason: "it has no GET /version (a server that predates it, or a URL that is not syn-api)",
      };
    }
    if (!response.ok || typeof data !== "object" || data === null) {
      return { kind: "unanswered", reason: `GET /version answered ${response.status}` };
    }
    return { kind: "reported", build: data };
  } catch (err) {
    // A refused connection, the timeout, or a body that is not JSON (a proxy's
    // HTML error page). If the server is unreachable the command is about to
    // say so itself.
    const reason = abort.signal.aborted
      ? `no answer within ${VERSION_PROBE_TIMEOUT_MS}ms`
      : err instanceof Error ? err.message : String(err);
    return { kind: "unanswered", reason };
  } finally {
    clearTimeout(timer);
  }
}

/** Compare release lines (major.minor). Patch and pre-release differences are
 * deliberately not skew: the two sides spell pre-releases differently (npm
 * `0.33.0-beta.1`, PEP 440 `0.33.0b5`), so comparing past minor would warn on
 * every beta. */
export function compareReleases(cliVersion: string, serverVersion: string | null | undefined): Skew {
  if (cliVersion === DEV_CLI_VERSION || typeof serverVersion !== "string") {
    return { kind: "undetermined" };
  }
  const cli = releaseLine(cliVersion);
  const server = releaseLine(serverVersion);
  if (cli === null || server === null) return { kind: "undetermined" };
  return cli === server
    ? { kind: "match" }
    : { kind: "mismatch", cli: cliVersion, server: serverVersion };
}

/** "M.m" from either spelling, or null when the string is not a version. */
function releaseLine(version: string): string | null {
  const match = /^v?(\d+)\.(\d+)(?:[.+\-a-z]|$)/i.exec(version.trim());
  return match ? `${Number(match[1])}.${Number(match[2])}` : null;
}
