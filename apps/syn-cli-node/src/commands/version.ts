import { compareReleases, probeServerBuild } from "../client/server-build.js";
import { api } from "../client/typed.js";
import { CLI_VERSION } from "../config.js";
import type { CommandDef } from "../framework/command.js";
import { BOLD, DIM, style } from "../output/ansi.js";
import { describeServerBuild, warnIfReleasesDiffer } from "../output/build.js";
import { print } from "../output/console.js";

/** Both sides of the version question (#1473). Line 1 is the CLI and is kept
 * exactly as it was, so `syn version | head -1` consumers are unaffected.
 *
 * Exits 0 whatever the server said: this reports what was found, and
 * `syn health` is the reachability gate. It does its own comparison, so the
 * framework preflight would only probe the same route twice. */
export const versionCommand: CommandDef = {
  name: "version",
  description: "Show CLI and server version",
  skipPreflight: true,
  handler: async () => {
    print(`${style("Syntropic137", BOLD)} v${CLI_VERSION}`);
    const server = await probeServerBuild();
    print(style(describeServerBuild(server, api.deployment), DIM));
    warnIfReleasesDiffer(compareReleases(CLI_VERSION, server));
  },
};
