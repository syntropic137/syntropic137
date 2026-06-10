// See ADR-066: thin API calls only - the API enforces the (name, version)
// must already exist in the lock projection. No git, no fs work here.
/**
 * `syn claude-plugin global <add|remove|list>` - manage the global plugin set.
 *
 * The CLI framework is one level deep, so the `global` group is implemented
 * as a single command that dispatches on its first positional - same pattern
 * as before. The `add` shape changed in Phase B: it now takes
 * (name, version) of an already-registered plugin instead of a ref. Use
 * `syn claude-plugin install <ref> --global` to do clone+register+enable in
 * one shot.
 */

import type { CommandDef, ParsedArgs } from "../../framework/command.js";
import { CLIError } from "../../framework/errors.js";
import { api, unwrap } from "../../client/typed.js";
import type { components } from "../../generated/api-types.js";
import { print, printError, printDim, printSuccess } from "../../output/console.js";
import { CYAN } from "../../output/ansi.js";
import { Table } from "../../output/table.js";
import { formatTimestamp } from "../../output/format.js";

type GlobalEntry = components["schemas"]["GlobalClaudePluginResponse"];
type GlobalList = components["schemas"]["GlobalClaudePluginListResponse"];
type RemoveResponse = components["schemas"]["RemoveGlobalClaudePluginResponse"];

export const globalCommand: CommandDef = {
  name: "global",
  description: "Manage the global Claude plugin set (subactions: add, remove, list)",
  args: [
    { name: "action", description: "add | remove | list", required: true },
    {
      name: "name_or_value",
      description: "Plugin name (add/remove) - 'add' also takes a version",
      required: false,
    },
    { name: "version", description: "Plugin version (add only)", required: false },
  ],
  handler: async (parsed: ParsedArgs) => {
    const action = parsed.positionals[0];
    if (!action) {
      throw new CLIError("Missing subaction. Expected one of: add, remove, list");
    }

    if (action === "list") {
      await runGlobalList();
      return;
    }
    if (action === "add") {
      const name = parsed.positionals[1];
      const version = parsed.positionals[2];
      if (!name || !version) {
        throw new CLIError(
          "Usage: syn claude-plugin global add <name> <version>\n" +
            "  Tip: 'syn claude-plugin install <ref> --global' clones and enables in one step.",
        );
      }
      await runGlobalAdd(name, version);
      return;
    }
    if (action === "remove") {
      const name = parsed.positionals[1];
      if (!name) {
        throw new CLIError(
          "Missing plugin name. Example: syn claude-plugin global remove my-plugin",
        );
      }
      await runGlobalRemove(name);
      return;
    }

    printError(`Unknown subaction: ${action}. Expected one of: add, remove, list`);
    throw new CLIError("Unknown subaction", 1);
  },
};

async function runGlobalAdd(name: string, version: string): Promise<void> {
  const result = await api.POST("/claude-plugins/global", {
    body: { name, version },
  });
  if (result.error !== undefined) {
    // The API returns 404 with detail.error_code=claude_plugin_not_registered.
    // Translate that into actionable user guidance instead of a raw HTTP dump.
    if (isNotRegisteredError(result.error)) {
      throw new CLIError(
        `${name}@${version} is not registered. Install it first:\n` +
          `  syn claude-plugin install <source>@${version}`,
      );
    }
    const detail =
      typeof result.error === "object" && result.error !== null && "detail" in result.error
        ? String((result.error as { detail: unknown }).detail)
        : String(result.error);
    throw new CLIError(`Add global claude plugin: ${detail}`);
  }
  const entry = result.data as GlobalEntry;
  printSuccess(`Added ${entry.name}@${entry.version} to global plugin set.`);
}

function isNotRegisteredError(err: unknown): boolean {
  if (typeof err !== "object" || err === null) return false;
  const detail = (err as { detail?: unknown }).detail;
  if (typeof detail !== "object" || detail === null) return false;
  const code = (detail as { error_code?: unknown }).error_code;
  return code === "claude_plugin_not_registered";
}

async function runGlobalRemove(name: string): Promise<void> {
  const result = unwrap<RemoveResponse>(
    await api.DELETE("/claude-plugins/global/{name}", {
      params: { path: { name } },
    }),
    "Remove global claude plugin",
  );
  printSuccess(`Removed ${result.name} from global plugin set.`);
}

async function runGlobalList(): Promise<void> {
  const data = unwrap<GlobalList>(
    await api.GET("/claude-plugins/global", {}),
    "List global claude plugins",
  );
  const items = data.plugins ?? [];
  if (items.length === 0) {
    printDim("No global claude plugins.");
    return;
  }
  renderGlobalTable(items);
}

function renderGlobalTable(items: readonly GlobalEntry[]): void {
  const table = new Table({ title: "Global Claude Plugins" });
  table.addColumn("NAME", { style: CYAN });
  table.addColumn("VERSION");
  table.addColumn("SOURCE");
  table.addColumn("ADDED");
  for (const e of items) {
    table.addRow(e.name, e.version, e.source_url, formatTimestamp(e.added_at));
  }
  print(table.render());
}
