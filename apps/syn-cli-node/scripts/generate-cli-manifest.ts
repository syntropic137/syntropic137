/**
 * Write the CLI command manifest: every group, command, positional argument
 * and option the shipped `syn` binary accepts, read from the same registry the
 * CLI dispatches from.
 *
 * The docs-drift gate (`scripts/check_docs_drift.py`) validates every `syn`
 * command in the public docs against this file, so a documented subcommand or
 * flag the CLI rejects fails the build instead of a reader. It runs under
 * `just codegen`, and `codegen-check` fails when the committed copy is stale.
 *
 * Usage:
 *   pnpm --filter @syntropic137/cli generate:manifest
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import type { CommandDef } from "../src/framework/command.js";
import { commandGroups, rootCommands } from "../src/registry.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUTPUT = path.resolve(__dirname, "../cli-manifest.json");

interface OptionEntry {
  name: string;
  short: string | null;
  takes_value: boolean;
}

interface CommandEntry {
  name: string;
  args: string[];
  options: OptionEntry[];
}

interface GroupEntry {
  name: string;
  commands: CommandEntry[];
}

interface Manifest {
  /** Accepted by every command and group: the parser adds it to each one. */
  global_options: OptionEntry[];
  /** Accepted only as the first argument, before any command. */
  top_level_flags: string[];
  root_commands: CommandEntry[];
  groups: GroupEntry[];
}

function commandEntry(def: CommandDef): CommandEntry {
  const options = Object.entries(def.options ?? {})
    .map(([name, opt]) => ({ name, short: opt.short ?? null, takes_value: opt.type === "string" }))
    .sort((a, b) => a.name.localeCompare(b.name));
  return { name: def.name, args: (def.args ?? []).map((a) => a.name), options };
}

function byName<T extends { name: string }>(a: T, b: T): number {
  return a.name.localeCompare(b.name);
}

function buildManifest(): Manifest {
  return {
    // Mirrors buildOptionsConfig in src/framework/cli.ts.
    global_options: [{ name: "help", short: "h", takes_value: false }],
    // Mirrors CLI.dispatch in src/framework/cli.ts.
    top_level_flags: ["--help", "-h", "--version"],
    root_commands: rootCommands.map(commandEntry).sort(byName),
    groups: commandGroups
      .map((g) => ({ name: g.name, commands: [...g.commands.values()].map(commandEntry).sort(byName) }))
      .sort(byName),
  };
}

fs.writeFileSync(OUTPUT, JSON.stringify(buildManifest(), null, 2) + "\n");
console.log(`Wrote ${path.relative(process.cwd(), OUTPUT)}`);
