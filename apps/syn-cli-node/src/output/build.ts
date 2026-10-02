/**
 * How a server build reads to a person. Shared by `syn health` and `syn version`
 * so "which build answered" is one sentence, not two that drift apart.
 */

import type { BuildInfo, ReleaseSkew, ServerBuild } from "../client/server-build.js";
import { printWarning } from "./console.js";

/** Which build answered. The release always; the image tag and commit only
 * when the image build stamped them, since an unstamped build reports null and
 * printing "commit: null" tells a reader nothing they can act on.
 *
 * THREE STATES, NOT TWO, and the third is the one that used to crash. `build`
 * is required by the CURRENT schema, but this CLI ships to npm and the server
 * is deployed separately, so a new CLI meets an old server routinely — and an
 * old server's /health has no `build` key at all. `openapi-fetch` does no
 * runtime validation, so the schema's guarantee is a compile-time one only:
 * reading `build.image_tag` on that payload threw a TypeError before anything
 * was printed, turning "is the new build live yet?" into a crash whose message
 * named neither the server nor its version.
 *
 * So the absent block is a state with its own sentence. A server too old to
 * report its build identity is not the same fact as a server that reported it
 * as unreadable (`version: null`), and both are different again from a release
 * we know — a reader chasing a rollout needs to tell all three apart. None of
 * them is ever filled in with a plausible number: the whole point of #1380 is
 * that a wrong release misleads a reader who a missing one would have sent
 * looking. */
export function describeBuild(build: BuildInfo | undefined): string {
  if (!build) {
    return "syn-api build identity not reported — this server predates /health carrying it (#1380)";
  }
  const stamps = [build.image_tag, build.commit].filter((s): s is string => Boolean(s));
  const release = build.version ?? "release unknown (package metadata unavailable)";
  return `syn-api ${release}` + (stamps.length > 0 ? ` (${stamps.join(", ")})` : "");
}

/** Line 2 of `syn version`: the build that answered, or why none did. Names
 * the deployment so the report says where the request actually went. */
export function describeServerBuild(server: ServerBuild, deployment: string): string {
  switch (server.kind) {
    case "reported":
      return describeBuild(server.build);
    case "no-version-route":
      return `syn-api at ${deployment} has no GET /version: a release older than that route, or not a syn-api URL`;
    case "unanswered":
      return `syn-api not reached at ${deployment}: ${server.reason}`;
  }
}

/** Why a route this CLI knows answered with the router's 404: the server is
 * older than the feature. Names the build when the server reported one; when
 * it did not, says what is known and stops there. A /version that is missing
 * or unanswered is undetermined, so this never claims a release it did not
 * read, and never calls it a mismatch (#1494). */
export function describeMissingRoute(server: ServerBuild, deployment: string, route: string): string {
  const missing = `has no ${route}; this server predates the feature`;
  switch (server.kind) {
    case "reported":
      return `${describeBuild(server.build)} at ${deployment} ${missing}. Upgrade the server to use this command.`;
    case "no-version-route":
      return `syn-api at ${deployment} ${missing}, and is too old to report its version (no GET /version), or is not a syn-api URL.`;
    case "unanswered":
      return `syn-api at ${deployment} ${missing}. Its version could not be read: ${server.reason}.`;
  }
}

/** One stderr line when, and only when, the release lines provably differ.
 * Undetermined is silent: if the server cannot be reached the command is about
 * to say so itself, and two messages for one cause is noise. */
export function warnIfReleasesDiffer(skew: ReleaseSkew): void {
  if (skew.kind !== "mismatch") return;
  printWarning(
    `syn CLI ${skew.cli} is talking to syn-api ${skew.server}. ` +
      `Releases differ (${skew.cliLine} vs ${skew.serverLine}); commands may fail in ways that look unrelated. ` +
      "Install a matching CLI.",
  );
}
