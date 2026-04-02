/**
 * Marketplace command group — wires all marketplace subcommands.
 */

import { CommandGroup } from "../../framework/command.js";
import { addCommand, listMarkeplaceCommand, removeCommand, refreshCommand } from "./registry.js";

export const marketplaceGroup = new CommandGroup(
  "marketplace",
  "Manage workflow marketplace registries",
);

marketplaceGroup
  .command(addCommand)
  .command(listMarkeplaceCommand)
  .command(removeCommand)
  .command(refreshCommand);
