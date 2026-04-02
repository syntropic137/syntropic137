/**
 * Configuration management commands — show, validate, env.
 * Port of apps/syn-cli/src/syn_cli/commands/config.py
 */

import { CommandGroup, type CommandDef, type ParsedArgs } from "../framework/command.js";
import { CLIError } from "../framework/errors.js";
import { apiGet } from "../client/api.js";
import { print } from "../output/console.js";
import { style, BOLD, GREEN, RED, YELLOW, BLUE } from "../output/ansi.js";
import { Table } from "../output/table.js";

const showCommand: CommandDef = {
  name: "show",
  description: "Display current configuration",
  options: {
    "show-secrets": { type: "boolean", description: "Show secret values", default: false },
  },
  handler: async (parsed: ParsedArgs) => {
    const showSecrets = parsed.values["show-secrets"] === true;
    const snapshot = await apiGet<Record<string, Record<string, unknown>>>("/config", {
      params: { show_secrets: String(showSecrets) },
    });

    for (const section of ["app", "database", "agents", "storage"]) {
      const data = snapshot[section];
      if (!data) continue;
      print(`\n${style(section.charAt(0).toUpperCase() + section.slice(1), BOLD)}`);
      for (const [k, v] of Object.entries(data)) {
        print(`  ${k}: ${String(v)}`);
      }
    }
  },
};

const validateCommand: CommandDef = {
  name: "validate",
  description: "Validate configuration and show issues",
  handler: async () => {
    print("Validating configuration...\n");

    const data = await apiGet<Record<string, unknown>>("/config/validate");
    const issues = (data["issues"] ?? []) as Record<string, string>[];

    if (issues.length === 0) {
      print(style("No issues found.", GREEN));
      return;
    }

    const table = new Table({ title: "Configuration Issues" });
    table.addColumn("Level");
    table.addColumn("Category");
    table.addColumn("Message");

    const levelStyles: Record<string, string> = { error: RED, warning: YELLOW, info: BLUE };
    let hasErrors = false;

    for (const issue of issues) {
      const level = issue["level"] ?? "info";
      const levelColor = levelStyles[level];
      table.addRow(
        levelColor ? style(level, levelColor) : level,
        issue["category"] ?? "",
        issue["message"] ?? "",
      );
      if (level === "error") hasErrors = true;
    }
    table.print();

    if (hasErrors) {
      print(`\n${style("Configuration has errors.", RED)}`);
      throw new CLIError("Config errors", 1);
    }
  },
};

const envCommand: CommandDef = {
  name: "env",
  description: "Show environment variable template",
  handler: async () => {
    const data = await apiGet<Record<string, unknown>>("/config/env");
    const template = typeof data === "string" ? data : String(data["template"] ?? JSON.stringify(data));
    print(template);
  },
};

export const configGroup = new CommandGroup("config", "Configuration management");
configGroup.command(showCommand).command(validateCommand).command(envCommand);
