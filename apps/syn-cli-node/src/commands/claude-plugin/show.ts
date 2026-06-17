// See ADR-066: thin read-only call; no git, no fs.
/**
 * `syn claude-plugin show <name> <version>` - look up one lock entry.
 */

import type { CommandDef, ParsedArgs } from "../../framework/command.js";
import { CLIError } from "../../framework/errors.js";
import { api, unwrap } from "../../client/typed.js";
import type { components } from "../../generated/api-types.js";
import { print } from "../../output/console.js";
import { style, BOLD } from "../../output/ansi.js";
import { formatTimestamp } from "../../output/format.js";

type LockEntry = components["schemas"]["ClaudePluginLockResponse"];

export const showCommand: CommandDef = {
  name: "show",
  description: "Show registered Claude plugin detail",
  args: [
    { name: "name", description: "Plugin name", required: true },
    { name: "version", description: "Plugin version", required: true },
  ],
  handler: async (parsed: ParsedArgs) => {
    const name = parsed.positionals[0];
    const version = parsed.positionals[1];
    if (!name) throw new CLIError("Missing required argument: name");
    if (!version) throw new CLIError("Missing required argument: version");

    const entry = unwrap<LockEntry>(
      await api.GET("/claude-plugins/{name}/{version}", {
        params: { path: { name, version } },
      }),
      "Show claude plugin",
    );

    print(`${style("Name:", BOLD)}               ${entry.name}`);
    print(`${style("Version:", BOLD)}            ${entry.version}`);
    print(`${style("Source:", BOLD)}             ${entry.source_url}`);
    print(`${style("Resolved SHA:", BOLD)}       ${entry.resolved_sha}`);
    print(`${style("Tree storage:", BOLD)}       ${entry.tree_storage_prefix}`);
    print(`${style("Registered:", BOLD)}         ${formatTimestamp(entry.registered_at)}`);
  },
};
