/**
 * Marketplace registry management — add, list, remove, refresh.
 * Port of apps/syn-cli/src/syn_cli/commands/marketplace/_registry.py
 */

import fs from "node:fs";
import path from "node:path";
import type { CommandDef, ParsedArgs } from "../../framework/command.js";
import { CLIError } from "../../framework/errors.js";
import { printError, printSuccess, print, printDim } from "../../output/console.js";
import { style, BOLD, CYAN, GREEN, RED } from "../../output/ansi.js";
import { formatTimestamp } from "../../output/format.js";
import { Table } from "../../output/table.js";
import { synPath } from "../../persistence/store.js";
import {
  fetchMarketplaceJson,
  loadRegistries,
  refreshIndex,
  saveCachedIndex,
  saveRegistries,
  validateRegistryName,
} from "../../marketplace/client.js";
import type { RegistryEntry } from "../../marketplace/models.js";

// ---------------------------------------------------------------------------
// add
// ---------------------------------------------------------------------------

export const addCommand: CommandDef = {
  name: "add",
  description: "Register a GitHub repo as a workflow marketplace",
  args: [{ name: "repo", description: "GitHub repo (org/repo shorthand)", required: true }],
  options: {
    ref: { type: "string", short: "r", description: "Git branch or tag", default: "main" },
    name: { type: "string", short: "n", description: "Override registry name" },
  },
  handler: async (parsed: ParsedArgs) => {
    const repo = parsed.positionals[0];
    if (!repo) {
      printError("Missing required argument: repo");
      throw new CLIError("Missing argument", 1);
    }

    const ref = (parsed.values["ref"] as string | undefined) ?? "main";
    const nameOverride = parsed.values["name"] as string | undefined;

    print(`Fetching marketplace.json from ${style(repo, CYAN)}@${ref}...`);

    let index;
    try {
      index = await fetchMarketplaceJson(repo, ref);
    } catch (err) {
      printError(err instanceof Error ? err.message : String(err));
      throw new CLIError("Fetch failed", 1);
    }

    const registryName = nameOverride ?? index.name;
    try {
      validateRegistryName(registryName);
    } catch (err) {
      printError(err instanceof Error ? err.message : String(err));
      throw new CLIError("Invalid name", 1);
    }

    const config = loadRegistries();
    if (config.registries[registryName]) {
      printError(`Marketplace '${registryName}' is already registered`);
      printDim("Use 'syn marketplace remove' first to re-register.");
      throw new CLIError("Already registered", 1);
    }

    const entry: RegistryEntry = {
      repo,
      ref,
      added_at: new Date().toISOString(),
    };

    saveRegistries({
      version: config.version,
      registries: { ...config.registries, [registryName]: entry },
    });

    saveCachedIndex(registryName, {
      fetched_at: new Date().toISOString(),
      index,
    });

    const pluginCount = index.plugins.length;
    printSuccess(
      `Added marketplace ${style(registryName, BOLD)} ` +
      `(${pluginCount} plugin${pluginCount !== 1 ? "s" : ""})`,
    );
  },
};

// ---------------------------------------------------------------------------
// list
// ---------------------------------------------------------------------------

export const listMarketplaceCommand: CommandDef = {
  name: "list",
  description: "List registered marketplace registries",
  handler: async () => {
    const config = loadRegistries();

    if (Object.keys(config.registries).length === 0) {
      printDim("No marketplaces registered.");
      printDim("Add one with: syn marketplace add syntropic137/workflow-library");
      return;
    }

    const table = new Table({ title: "Registered Marketplaces" });
    table.addColumn("Name", { style: BOLD });
    table.addColumn("Repo");
    table.addColumn("Ref");
    table.addColumn("Added");

    for (const [name, entry] of Object.entries(config.registries)) {
      table.addRow(
        name,
        entry.repo,
        entry.ref,
        formatTimestamp(entry.added_at),
      );
    }
    table.print();
  },
};

// ---------------------------------------------------------------------------
// remove
// ---------------------------------------------------------------------------

export const removeCommand: CommandDef = {
  name: "remove",
  description: "Remove a registered marketplace",
  args: [{ name: "name", description: "Registry name to remove", required: true }],
  handler: async (parsed: ParsedArgs) => {
    const name = parsed.positionals[0];
    if (!name) {
      printError("Missing required argument: name");
      throw new CLIError("Missing argument", 1);
    }

    const config = loadRegistries();
    if (!config.registries[name]) {
      printError(`Marketplace '${name}' is not registered`);
      throw new CLIError("Not found", 1);
    }

    const remaining: Record<string, RegistryEntry> = {};
    for (const [k, v] of Object.entries(config.registries)) {
      if (k !== name) remaining[k] = v;
    }
    saveRegistries({ version: config.version, registries: remaining });

    // Clean up cache
    try {
      validateRegistryName(name);
      const cachePath = path.join(synPath("marketplace", "cache"), `${name}.json`);
      if (fs.existsSync(cachePath)) fs.unlinkSync(cachePath);
    } catch {
      // Skip cleanup for unsafe names
    }

    printSuccess(`Removed marketplace ${style(name, BOLD)}`);
  },
};

// ---------------------------------------------------------------------------
// refresh
// ---------------------------------------------------------------------------

export const refreshCommand: CommandDef = {
  name: "refresh",
  description: "Force-refresh cached marketplace indexes",
  args: [{ name: "name", description: "Registry name (refreshes all if omitted)" }],
  handler: async (parsed: ParsedArgs) => {
    const nameFilter = parsed.positionals[0] as string | undefined;
    const config = loadRegistries();

    if (Object.keys(config.registries).length === 0) {
      printDim("No marketplaces registered.");
      return;
    }

    let targets: [string, RegistryEntry][];
    if (nameFilter) {
      const entry = config.registries[nameFilter];
      if (!entry) {
        printError(`Marketplace '${nameFilter}' is not registered`);
        throw new CLIError("Not found", 1);
      }
      targets = [[nameFilter, entry]];
    } else {
      targets = Object.entries(config.registries);
    }

    for (const [regName, entry] of targets) {
      process.stdout.write(`Refreshing ${style(regName, CYAN)}... `);
      try {
        const index = await refreshIndex(regName, entry, true);
        const pluginCount = index.plugins.length;
        print(`${style("done", GREEN)} (${pluginCount} plugin${pluginCount !== 1 ? "s" : ""})`);
      } catch (err) {
        print(`${style("failed", RED)} (${err instanceof Error ? err.message : String(err)})`);
      }
    }
  },
};
