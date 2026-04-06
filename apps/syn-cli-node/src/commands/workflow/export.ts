/**
 * Workflow export command.
 * Port of apps/syn-cli/src/syn_cli/commands/workflow/_export.py
 */

import fs from "node:fs";
import path from "node:path";
import type { CommandDef, ParsedArgs } from "../../framework/command.js";
import { CLIError } from "../../framework/errors.js";
import { api, unwrap } from "../../client/typed.js";
import { printError, printSuccess, print } from "../../output/console.js";
import { style, BOLD, CYAN, DIM, GREEN } from "../../output/ansi.js";

export const exportCommand: CommandDef = {
  name: "export",
  description: "Export a workflow as a distributable package or Claude Code plugin",
  args: [{ name: "workflow-id", description: "Workflow ID to export", required: true }],
  options: {
    format: { type: "string", short: "f", description: "Export format: 'package' (default) or 'plugin'", default: "package" },
    output: { type: "string", short: "o", description: "Output directory (created if absent)", default: "." },
  },
  handler: async (parsed: ParsedArgs) => {
    const workflowId = parsed.positionals[0];
    if (!workflowId) {
      printError("Missing required argument: workflow-id");
      throw new CLIError("Missing argument", 1);
    }

    const fmt = (parsed.values["format"] as string | undefined) ?? "package";
    if (fmt !== "package" && fmt !== "plugin") {
      printError(`Invalid format '${fmt}'. Must be 'package' or 'plugin'.`);
      throw new CLIError("Invalid format", 1);
    }

    const outputDir = (parsed.values["output"] as string | undefined) ?? ".";

    const data = unwrap(
      await api.GET("/workflows/{workflow_id}/export", {
        params: {
          path: { workflow_id: workflowId },
          query: { format: fmt },
        },
      }),
      "Failed to export workflow",
    );

    const files = data.files;
    if (Object.keys(files).length === 0) {
      printError("Export returned no files");
      throw new CLIError("Export empty", 1);
    }

    const outDir = path.resolve(outputDir);
    if (fs.existsSync(outDir)) {
      const entries = fs.readdirSync(outDir);
      if (entries.length > 0) {
        printError(`Output directory is not empty: ${outDir}`);
        throw new CLIError("Directory not empty", 1);
      }
    }

    // Write files with path traversal protection
    for (const [relPath, content] of Object.entries(files).sort(([a], [b]) => a.localeCompare(b))) {
      if (relPath.startsWith("/") || relPath.includes("..")) {
        printError(`Unsafe file path in export manifest: ${relPath}`);
        throw new CLIError("Path traversal", 1);
      }

      const filePath = path.resolve(outDir, relPath);
      if (!filePath.startsWith(outDir)) {
        printError(`Path escapes output directory: ${relPath}`);
        throw new CLIError("Path traversal", 1);
      }

      fs.mkdirSync(path.dirname(filePath), { recursive: true });
      fs.writeFileSync(filePath, content, "utf-8");
    }

    const workflowName = data.workflow_name;

    // Summary
    print("");
    print(style("Export Complete", GREEN));
    print(`  ${style(workflowName, BOLD)}`);
    print(`  Format: ${fmt}`);
    print(`  Output: ${outDir}`);
    print(`  Files: ${Object.keys(files).length}`);

    // File tree
    print("");
    print(style(`${path.basename(outDir)}/`, CYAN));
    const sortedPaths = Object.keys(files).sort();
    for (const relPath of sortedPaths) {
      const parts = relPath.split("/");
      const indent = "  ".repeat(parts.length);
      print(`${indent}${style(parts[parts.length - 1]!, DIM)}`);
    }

    printSuccess(`\nExported to ${outDir}`);
    print(`\nTo install: ${style(`syn workflow install ${outDir}`, CYAN)}`);
    if (fmt === "plugin") {
      print(`Plugin command: ${style(`/syn-${workflowName.toLowerCase().replace(/ /g, "-")}`, CYAN)}`);
    }
  },
};
