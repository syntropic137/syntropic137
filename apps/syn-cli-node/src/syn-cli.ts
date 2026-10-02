/**
 * The `syn` CLI as shipped: every registered command plus the server-version
 * preflight and the explanation of a route the server does not have. index.ts only runs it; tests build the same thing from here, so
 * a CLI that silently lost its preflight fails a test rather than an operator.
 */

import { explainMissingRoutes } from "./client/missing-route.js";
import { compareReleases, probeServerBuild, type ServerBuild } from "./client/server-build.js";
import { api } from "./client/typed.js";
import { CLI_DESCRIPTION, CLI_NAME, CLI_VERSION } from "./config.js";
import { CLI } from "./framework/cli.js";
import { warnIfReleasesDiffer } from "./output/build.js";
import { commandGroups, rootCommands } from "./registry.js";

export function createSynCli(): CLI {
  // One /version request per run, shared by the preflight and by the
  // explanation of a missing route, so the two can never name different builds.
  let probed: Promise<ServerBuild> | undefined;
  const serverBuild = (): Promise<ServerBuild> => (probed ??= probeServerBuild());
  api.use(explainMissingRoutes(serverBuild, api.deployment));

  const cli = new CLI({
    name: CLI_NAME,
    description: CLI_DESCRIPTION,
    version: CLI_VERSION,
    // Warn, before the command prints anything, when the server is a different
    // release line from this CLI (#1473). Never throws: the probe is total.
    preflight: async () => warnIfReleasesDiffer(compareReleases(CLI_VERSION, await serverBuild())),
  });
  for (const cmd of rootCommands) cli.addCommand(cmd);
  for (const group of commandGroups) cli.addGroup(group);
  return cli;
}
