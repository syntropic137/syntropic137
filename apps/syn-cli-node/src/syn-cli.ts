/**
 * The `syn` CLI as shipped: every registered command plus the server-version
 * preflight. index.ts only runs it; tests build the same thing from here, so
 * a CLI that silently lost its preflight fails a test rather than an operator.
 */

import { compareReleases, probeServerBuild } from "./client/server-build.js";
import { CLI_DESCRIPTION, CLI_NAME, CLI_VERSION } from "./config.js";
import { CLI } from "./framework/cli.js";
import { warnIfReleasesDiffer } from "./output/build.js";
import { commandGroups, rootCommands } from "./registry.js";

/** Warn, before the command prints anything, when the server is a different
 * release line from this CLI (#1473). Never throws: the probe is total. */
async function warnOnReleaseSkew(): Promise<void> {
  warnIfReleasesDiffer(compareReleases(CLI_VERSION, await probeServerBuild()));
}

export function createSynCli(): CLI {
  const cli = new CLI({
    name: CLI_NAME,
    description: CLI_DESCRIPTION,
    version: CLI_VERSION,
    preflight: warnOnReleaseSkew,
  });
  for (const cmd of rootCommands) cli.addCommand(cmd);
  for (const group of commandGroups) cli.addGroup(group);
  return cli;
}
