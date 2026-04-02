/**
 * Workflow marketplace discovery — search and info commands.
 * Port of apps/syn-cli/src/syn_cli/commands/workflow/_search.py
 */

import type { CommandDef, ParsedArgs } from "../../framework/command.js";
import { CLIError } from "../../framework/errors.js";
import { printError, print, printDim } from "../../output/console.js";
import { style, BOLD, DIM } from "../../output/ansi.js";
import { Table } from "../../output/table.js";
import { searchAllRegistries, resolvePluginByName } from "../../marketplace/client.js";

function truncate(text: string, maxLen: number): string {
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen - 3) + "...";
}

// ---------------------------------------------------------------------------
// search
// ---------------------------------------------------------------------------

export const searchCommand: CommandDef = {
  name: "search",
  description: "Search for workflows across registered marketplaces",
  args: [{ name: "query", description: "Search term (matches name, description, tags)" }],
  options: {
    category: { type: "string", short: "c", description: "Filter by category" },
    tag: { type: "string", short: "t", description: "Filter by tag" },
    registry: { type: "string", short: "r", description: "Search specific marketplace only" },
  },
  handler: async (parsed: ParsedArgs) => {
    const query = parsed.positionals[0] ?? "";
    const category = (parsed.values["category"] as string | undefined) ?? null;
    const tag = (parsed.values["tag"] as string | undefined) ?? null;
    const registryFilter = parsed.values["registry"] as string | undefined;

    let results = await searchAllRegistries(query, { category, tag });

    if (registryFilter) {
      results = results.filter(([rn]) => rn === registryFilter);
    }

    if (results.length === 0) {
      printDim("No workflows found.");
      if (!query && !category && !tag) {
        printDim("Add a marketplace first: syn marketplace add syntropic137/workflow-library");
      }
      return;
    }

    const table = new Table({ title: "Available Workflows" });
    table.addColumn("Name", { style: BOLD });
    table.addColumn("Version");
    table.addColumn("Category");
    table.addColumn("Description");
    table.addColumn("Registry", { style: DIM });

    for (const [regName, plugin] of results) {
      table.addRow(
        plugin.name,
        plugin.version,
        plugin.category || "-",
        truncate(plugin.description, 50),
        regName,
      );
    }
    table.print();

    const count = results.length;
    printDim(`\n${count} result${count !== 1 ? "s" : ""}. Install with: syn workflow install <name>`);
  },
};

// ---------------------------------------------------------------------------
// info
// ---------------------------------------------------------------------------

export const infoCommand: CommandDef = {
  name: "info",
  description: "Show details of a marketplace workflow plugin",
  args: [{ name: "name", description: "Plugin name from marketplace", required: true }],
  handler: async (parsed: ParsedArgs) => {
    const name = parsed.positionals[0];
    if (!name) {
      printError("Missing required argument: name");
      throw new CLIError("Missing argument", 1);
    }

    const result = await resolvePluginByName(name);

    if (result === null) {
      printError(`Plugin '${name}' not found in any registered marketplace`);
      printDim("Try: syn workflow search");
      throw new CLIError("Not found", 1);
    }

    const [regName, entry, plugin] = result;
    const tagsStr = plugin.tags.length > 0 ? plugin.tags.join(", ") : "-";

    print("");
    print(style(plugin.name, BOLD));
    print(`  ${style("Version:", BOLD)}     ${plugin.version}`);
    print(`  ${style("Description:", BOLD)} ${plugin.description || "-"}`);
    print(`  ${style("Category:", BOLD)}    ${plugin.category || "-"}`);
    print(`  ${style("Tags:", BOLD)}        ${tagsStr}`);
    print(`  ${style("Source:", BOLD)}      ${entry.repo} (${plugin.source})`);
    print(`  ${style("Registry:", BOLD)}    ${regName}`);
    print("");
    printDim(`Install: syn workflow install ${plugin.name}`);
  },
};
