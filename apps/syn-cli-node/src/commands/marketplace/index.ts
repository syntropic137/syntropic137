/**
 * Marketplace command group — wires all marketplace subcommands.
 */

import { CommandGroup } from "../../framework/command.js";
import { addCommand, listMarketplaceCommand, removeCommand, refreshCommand } from "./registry.js";

export const marketplaceGroup = new CommandGroup(
  "marketplace",
  "Manage workflow marketplace registries",
);

marketplaceGroup
  .command(addCommand)
  .command(listMarketplaceCommand)
  .command(removeCommand)
  .command(refreshCommand);
