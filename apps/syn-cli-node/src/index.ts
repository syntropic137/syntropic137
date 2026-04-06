import { CLI_DESCRIPTION, CLI_NAME, CLI_VERSION } from "./config.js";
import { CLI } from "./framework/cli.js";
import { commandGroups, rootCommands } from "./registry.js";

const cli = new CLI({
  name: CLI_NAME,
  description: CLI_DESCRIPTION,
  version: CLI_VERSION,
});

for (const cmd of rootCommands) {
  cli.addCommand(cmd);
}

for (const group of commandGroups) {
  cli.addGroup(group);
}

cli.run();
