/**
 * Workflow command group — wires all workflow subcommands.
 */

import { CommandGroup } from "../../framework/command.js";
import { createCommand, listCommand, showCommand, validateCommand, deleteCommand } from "./crud.js";
import { runCommand, statusCommand } from "./run.js";
import { installCommand, installedCommand, initCommand } from "./install.js";
import { exportCommand } from "./export.js";
import { searchCommand, infoCommand } from "./search.js";
import { updateCommand, uninstallCommand } from "./update.js";

export const workflowGroup = new CommandGroup(
  "workflow",
  "Manage workflows - create, list, run, and inspect",
);

workflowGroup
  .command(createCommand)
  .command(listCommand)
  .command(showCommand)
  .command(validateCommand)
  .command(deleteCommand)
  .command(runCommand)
  .command(statusCommand)
  .command(installCommand)
  .command(installedCommand)
  .command(initCommand)
  .command(exportCommand)
  .command(searchCommand)
  .command(infoCommand)
  .command(updateCommand)
  .command(uninstallCommand);
