// See ADR-066: this file wires the claude-plugin CLI command group. The
// install/global commands do local git work; list/show/global itself only
// hit thin API endpoints.
/**
 * Claude plugin command group definition.
 *
 * Subcommands (#726, Phase B):
 *   install <ref> [--global]   - clone + register; optionally enable globally
 *   list                       - list every registered plugin (lock projection)
 *   show <name> <version>      - show one lock entry
 *   global <add|remove|list>   - manage the global plugin set
 */

import { CommandGroup } from "../../framework/command.js";
import { installCommand } from "./install.js";
import { installedCommand } from "./installed.js";
import { listCommand } from "./list.js";
import { showCommand } from "./show.js";
import { globalCommand } from "./global.js";

export const claudePluginGroup = new CommandGroup(
  "claude-plugin",
  "Manage Claude Code plugins registered with Syntropic137",
);

claudePluginGroup
  .command(installCommand)
  .command(installedCommand)
  .command(listCommand)
  .command(showCommand)
  .command(globalCommand);
