/**
 * Generate MDX documentation for the syn CLI from Node CLI command metadata.
 *
 * This script imports all CommandGroup and CommandDef instances from the Node CLI,
 * walks their metadata (name, description, args, options), and generates MDX files
 * for the Fumadocs-based documentation site.
 *
 * Usage:
 *   pnpm --filter @syntropic137/cli generate:docs
 *   # or directly:
 *   tsx scripts/generate-cli-docs.ts
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import type { ArgDef, CommandDef, OptionDef } from "../src/framework/command.js";
import { CommandGroup } from "../src/framework/command.js";

// ---------------------------------------------------------------------------
// Import from the shared registry — single source of truth.
// Adding a new command group to registry.ts automatically includes it here.
// ---------------------------------------------------------------------------

import { commandGroups, rootCommands as registryRootCommands } from "../src/registry.js";

// ---------------------------------------------------------------------------
// Path setup
// ---------------------------------------------------------------------------

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUTPUT_DIR = path.resolve(__dirname, "../../syn-docs/content/docs/cli");

// ---------------------------------------------------------------------------
// Data models (plain objects — no handler references)
// ---------------------------------------------------------------------------

interface ParamInfo {
  name: string;
  paramType: "argument" | "option";
  typeStr: string;
  required: boolean;
  defaultValue: string | undefined;
  help: string;
  flags: string[];
}

interface CmdInfo {
  name: string;
  help: string;
  params: ParamInfo[];
}

interface GrpInfo {
  name: string;
  help: string;
  commands: CmdInfo[];
}

// ---------------------------------------------------------------------------
// Extraction
// ---------------------------------------------------------------------------

function typeLabel(opt: OptionDef): string {
  return opt.type === "string" ? "text" : "boolean";
}

function defaultStr(opt: OptionDef): string | undefined {
  if (opt.default === undefined) return undefined;
  if (typeof opt.default === "boolean") return String(opt.default);
  return String(opt.default);
}

function buildFlags(name: string, opt: OptionDef): string[] {
  const flags = [`--${name}`];
  if (opt.short) flags.push(`-${opt.short}`);
  return flags;
}

function extractCommand(def: CommandDef): CmdInfo {
  const params: ParamInfo[] = [];

  if (def.args) {
    for (const arg of def.args) {
      params.push({
        name: arg.name,
        paramType: "argument",
        typeStr: "text",
        required: arg.required !== false,
        defaultValue: undefined,
        help: arg.description,
        flags: [],
      });
    }
  }

  if (def.options) {
    for (const [name, opt] of Object.entries(def.options)) {
      params.push({
        name,
        paramType: "option",
        typeStr: typeLabel(opt),
        required: false,
        defaultValue: defaultStr(opt),
        help: opt.description,
        flags: buildFlags(name, opt),
      });
    }
  }

  return {
    name: def.name,
    help: def.description,
    params,
  };
}

function extractGroup(group: CommandGroup): GrpInfo {
  const commands: CmdInfo[] = [];
  for (const [, def] of [...group.commands].sort(([a], [b]) => a.localeCompare(b))) {
    commands.push(extractCommand(def));
  }
  return {
    name: group.name,
    help: group.description,
    commands,
  };
}

// ---------------------------------------------------------------------------
// MDX rendering — matches the format of the previous Python generator
// ---------------------------------------------------------------------------

function renderArgRows(args: ParamInfo[]): string[] {
  const lines = [
    "**Arguments:**",
    "",
    "| Name | Type | Required | Description |",
    "|------|------|----------|-------------|",
  ];
  for (const a of args) {
    const req = a.required ? "Yes" : "No";
    lines.push(`| \`${a.name}\` | \`${a.typeStr}\` | ${req} | ${a.help} |`);
  }
  lines.push("");
  return lines;
}

function renderOptRows(opts: ParamInfo[]): string[] {
  const lines = [
    "**Options:**",
    "",
    "| Flag | Type | Default | Description |",
    "|------|------|---------|-------------|",
  ];
  for (const o of opts) {
    const flags = o.flags.map((f) => `\`${f}\``).join(", ");
    const def = o.defaultValue !== undefined ? `\`${o.defaultValue}\`` : "---";
    lines.push(`| ${flags} | \`${o.typeStr}\` | ${def} | ${o.help} |`);
  }
  lines.push("");
  return lines;
}

function renderParamTable(params: ParamInfo[]): string {
  const args = params.filter((p) => p.paramType === "argument");
  const opts = params.filter((p) => p.paramType === "option");
  const lines: string[] = [];
  if (args.length > 0) lines.push(...renderArgRows(args));
  if (opts.length > 0) lines.push(...renderOptRows(opts));
  return lines.join("\n");
}

function formatParamUsage(p: ParamInfo): string | null {
  if (p.paramType === "argument") {
    return p.required ? `<${p.name}>` : `[${p.name}]`;
  }
  if (p.paramType === "option" && p.required && p.flags.length > 0) {
    return `${p.flags[0]} <${p.name}>`;
  }
  return null;
}

function buildUsageLine(prefix: string, params: ParamInfo[]): string {
  const parts = [prefix];
  for (const p of params) {
    const usage = formatParamUsage(p);
    if (usage) parts.push(usage);
  }
  if (params.some((p) => p.paramType === "option")) parts.push("[options]");
  return parts.join(" ");
}

function renderCommandMdx(groupName: string, cmd: CmdInfo): string[] {
  const lines: string[] = [];
  lines.push(`## \`syn ${groupName} ${cmd.name}\``);
  lines.push("");
  if (cmd.help) {
    lines.push(cmd.help);
    lines.push("");
  }
  lines.push("```bash");
  lines.push(buildUsageLine(`syn ${groupName} ${cmd.name}`, cmd.params));
  lines.push("```");
  lines.push("");
  if (cmd.params.length > 0) {
    lines.push(renderParamTable(cmd.params));
  }
  lines.push("---");
  lines.push("");
  return lines;
}

function renderGroupMdx(group: GrpInfo): string {
  const lines: string[] = [
    "---",
    `title: syn ${group.name}`,
    `description: "${group.help}"`,
    "---",
    "",
    group.help,
    "",
  ];
  for (const cmd of group.commands) {
    lines.push(...renderCommandMdx(group.name, cmd));
  }
  return lines.join("\n");
}

function renderIndexMdx(groups: GrpInfo[], topLevel: CmdInfo[]): string {
  const lines: string[] = [];

  lines.push("---");
  lines.push("title: CLI Reference");
  lines.push("description: Command-line interface for Syntropic137.");
  lines.push("---");
  lines.push("");
  lines.push(
    "The `syn` CLI provides commands for managing workflows, agents, and the Syntropic137",
  );
  lines.push("platform from your terminal.");
  lines.push("");
  lines.push("## Installation");
  lines.push("");
  lines.push("```bash");
  lines.push("npm install -g @syntropic137/cli");
  lines.push("syn --help");
  lines.push("```");
  lines.push("");

  if (topLevel.length > 0) {
    lines.push("## Global Commands");
    lines.push("");
    lines.push("| Command | Description |");
    lines.push("|---------|-------------|");
    for (const cmd of topLevel) {
      lines.push(`| \`syn ${cmd.name}\` | ${cmd.help} |`);
    }
    lines.push("");
  }

  lines.push("## Command Groups");
  lines.push("");
  lines.push("| Group | Description |");
  lines.push("|-------|-------------|");
  for (const g of groups) {
    lines.push(`| [\`syn ${g.name}\`](/docs/cli/${g.name}) | ${g.help} |`);
  }
  lines.push("");

  lines.push("## Global Options");
  lines.push("");
  lines.push("| Option | Description |");
  lines.push("|--------|-------------|");
  lines.push("| `--help` | Show help message |");
  lines.push("");

  return lines.join("\n");
}

function renderMetaJson(groups: GrpInfo[]): string {
  const pages = ["index", ...groups.map((g) => g.name)];
  const meta = {
    title: "CLI Reference",
    root: true,
    pages,
  };
  return JSON.stringify(meta, null, 2) + "\n";
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

function main(): void {
  fs.mkdirSync(OUTPUT_DIR, { recursive: true });

  // Command groups and root commands come from the shared registry —
  // no manual list to maintain. See src/registry.ts.
  const groups = [...commandGroups].map(extractGroup);
  const topLevel = [...registryRootCommands].map(extractCommand);

  const totalCommands = groups.reduce((sum, g) => sum + g.commands.length, 0) + topLevel.length;
  console.log(
    `Extracted ${groups.length} command groups, ` +
      `${topLevel.length} top-level commands ` +
      `(${totalCommands} total)`,
  );

  // Track generated files to clean up stale ones
  const generatedFiles = new Set<string>(["index.mdx", "meta.json"]);

  // Write index
  const indexPath = path.join(OUTPUT_DIR, "index.mdx");
  fs.writeFileSync(indexPath, renderIndexMdx(groups, topLevel));
  console.log(`  wrote content/docs/cli/index.mdx`);

  // Write meta.json
  const metaPath = path.join(OUTPUT_DIR, "meta.json");
  fs.writeFileSync(metaPath, renderMetaJson(groups));
  console.log(`  wrote content/docs/cli/meta.json`);

  // Write per-group pages
  for (const group of groups) {
    const filename = `${group.name}.mdx`;
    generatedFiles.add(filename);
    const pagePath = path.join(OUTPUT_DIR, filename);
    fs.writeFileSync(pagePath, renderGroupMdx(group));
    console.log(`  wrote content/docs/cli/${filename}`);
  }

  // Remove stale .mdx files from previous generations
  for (const file of fs.readdirSync(OUTPUT_DIR)) {
    if (file.endsWith(".mdx") && !generatedFiles.has(file)) {
      fs.unlinkSync(path.join(OUTPUT_DIR, file));
      console.log(`  removed stale content/docs/cli/${file}`);
    }
  }

  console.log(`\nDone. ${groups.length + 2} files written to content/docs/cli/`);
}

main();
