/**
 * Skill command group (#826).
 *
 * Subcommands:
 *   list          - every registered skill
 *   show <name>   - every registration sharing a name
 *   add <ref>     - register from a local path or a pinned remote ref
 *
 * Skills normally register themselves during `syn workflow install`; these
 * commands exist so registration state can be inspected and repaired.
 */

import { CommandGroup } from "../../framework/command.js";
import { addCommand } from "./add.js";
import { listCommand } from "./list.js";
import { showCommand } from "./show.js";

export const skillGroup = new CommandGroup(
  "skill",
  "Inspect and register agent skills",
);

skillGroup.command(listCommand).command(showCommand).command(addCommand);
