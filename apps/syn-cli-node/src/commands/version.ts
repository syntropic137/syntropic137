import { CLI_VERSION } from "../config.js";
import type { CommandDef } from "../framework/command.js";
import { BOLD, style } from "../output/ansi.js";
import { print } from "../output/console.js";

export const versionCommand: CommandDef = {
  name: "version",
  description: "Show version information",
  handler: () => {
    print(`${style("Syntropic137", BOLD)} v${CLI_VERSION}`);
  },
};
