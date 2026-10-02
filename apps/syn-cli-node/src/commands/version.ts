import { api } from "../client/typed.js";
import {
  compareReleases,
  probeServerBuild,
  type BuildInfo,
  type ServerBuild,
} from "../client/server-build.js";
import { CLI_VERSION } from "../config.js";
import type { CommandDef } from "../framework/command.js";
import { BOLD, DIM, style } from "../output/ansi.js";
import { print, printWarning } from "../output/console.js";

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
 * looking.
 *
 * Shared by `syn health` and `syn version` so "which build answered" has one
 * sentence, not two that drift. */
export function describeBuild(build: BuildInfo | undefined): string {
  if (!build) {
    return "syn-api build identity not reported — this server predates /health carrying it (#1380)";
  }
  const stamps = [build.image_tag, build.commit].filter((s): s is string => Boolean(s));
  const release = build.version ?? "release unknown (package metadata unavailable)";
  return `syn-api ${release}` + (stamps.length > 0 ? ` (${stamps.join(", ")})` : "");
}

/** The CLI's preflight (#1473): warn on stderr when the server provably runs
 * another release line, and say nothing otherwise. An unreachable server is
 * reported by the command itself, and two messages for one cause is noise.
 *
 * Returns what it found so `syn version` reports the same probe it warned from. */
export async function warnOnReleaseSkew(cliVersion: string): Promise<ServerBuild> {
  const server = await probeServerBuild();
  if (server.kind === "reported") {
    const skew = compareReleases(cliVersion, server.build.version);
    if (skew.kind === "mismatch") {
      printWarning(
        `syn CLI ${skew.cli} is talking to syn-api ${skew.server}. Releases differ; ` +
          "commands may fail in ways that look unrelated. Install a matching CLI.",
      );
    }
  }
  return server;
}

export const versionCommand: CommandDef = {
  name: "version",
  description: "Show CLI and server version",
  // It runs the same check itself and reports it; the preflight would probe twice.
  skipPreflight: true,
  handler: async () => {
    // Line 1 is unchanged so `syn version | head -1` keeps meaning the CLI.
    print(`${style("Syntropic137", BOLD)} v${CLI_VERSION}`);
    const server = await warnOnReleaseSkew(CLI_VERSION);
    // Exit 0 whatever the server said: this answers "what am I and what did I
    // find". `syn health` is the reachability gate.
    print(
      style(
        server.kind === "reported"
          ? describeBuild(server.build)
          : `syn-api not identified at ${api.deployment}: ${server.reason}`,
        DIM,
      ),
    );
  },
};
