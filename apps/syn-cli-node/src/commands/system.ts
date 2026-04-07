/**
 * System management commands — CRUD + observability.
 * Port of apps/syn-cli/src/syn_cli/commands/system/_crud.py + _observability.py
 */

import { CommandGroup, type CommandDef, type ParsedArgs } from "../framework/command.js";
import { CLIError } from "../framework/errors.js";
import { api, unwrap } from "../client/typed.js";
import { print, printError, printDim, printSuccess } from "../output/console.js";
import { style, BOLD, CYAN, DIM, GREEN, RED, YELLOW } from "../output/ansi.js";
import { formatCost, formatDuration, formatStatus, formatTimestamp, formatTokens } from "../output/format.js";
import { Table } from "../output/table.js";


function reqId(parsed: ParsedArgs): string {
  const id = parsed.positionals[0];
  if (!id) { printError("Missing system-id"); throw new CLIError("Missing argument", 1); }
  return id;
}

// --- CRUD ---

const createCommand: CommandDef = {
  name: "create",
  description: "Create a new system",
  options: {
    name: { type: "string", short: "n", description: "System name" },
    description: { type: "string", short: "d", description: "System description" },
    org: { type: "string", short: "o", description: "Organization ID" },
  },
  handler: async (parsed: ParsedArgs) => {
    const name = parsed.values["name"] as string | undefined;
    if (!name) { printError("Missing --name"); throw new CLIError("Missing option", 1); }

    const desc = parsed.values["description"] as string | undefined;
    const org = parsed.values["org"] as string | undefined;
    if (!org) { printError("Missing --org"); throw new CLIError("Missing option", 1); }

    const body = {
      name,
      organization_id: org,
      description: desc ?? "",
      created_by: "cli",
    };

    const d = unwrap(await api.POST("/systems", { body }), "Create system");
    printSuccess(`System created: ${d.system_id}`);
    print(`  Name: ${d.name}`);
  },
};

const listCommand: CommandDef = {
  name: "list",
  description: "List all systems",
  options: {
    org: { type: "string", short: "o", description: "Filter by organization" },
  },
  handler: async (parsed: ParsedArgs) => {
    const d = unwrap(await api.GET("/systems", {
      params: {
        query: {
          organization_id: (parsed.values["org"] as string | undefined) ?? null,
        },
      },
    }), "List systems");
    const items = d.systems ?? [];
    if (items.length === 0) { printDim("No systems found."); return; }

    const table = new Table({ title: "Systems" });
    table.addColumn("ID", { style: CYAN });
    table.addColumn("Name");
    table.addColumn("Org", { style: DIM });
    table.addColumn("Repos", { align: "right" });

    for (const s of items) {
      table.addRow(
        s.system_id,
        s.name,
        s.organization_id || "\u2014",
        String(s.repo_count),
      );
    }
    table.print();
  },
};

const showCommand: CommandDef = {
  name: "show",
  description: "Show system details",
  args: [{ name: "system-id", description: "System ID", required: true }],
  handler: async (parsed: ParsedArgs) => {
    const id = reqId(parsed);
    const d = unwrap(await api.GET("/systems/{system_id}", { params: { path: { system_id: id } } }), "Get system");
    print(`${style("System:", BOLD)} ${d.name}`);
    print(`  ID:          ${d.system_id}`);
    if (d.description) print(`  Description: ${d.description}`);
    if (d.organization_id) print(`  Org:         ${d.organization_id}`);
    print(`  Repos:       ${d.repo_count}`);
  },
};

const updateCommand: CommandDef = {
  name: "update",
  description: "Update a system",
  args: [{ name: "system-id", description: "System ID", required: true }],
  options: {
    name: { type: "string", short: "n", description: "New name" },
    description: { type: "string", short: "d", description: "New description" },
  },
  handler: async (parsed: ParsedArgs) => {
    const id = reqId(parsed);
    const name = parsed.values["name"] as string | undefined;
    const desc = parsed.values["description"] as string | undefined;
    if (!name && !desc) { printError("Nothing to update. Use --name or --description."); throw new CLIError("No updates", 1); }

    const body = {
      ...(name ? { name } : {}),
      ...(desc ? { description: desc } : {}),
    };
    unwrap(await api.PUT("/systems/{system_id}", { params: { path: { system_id: id } }, body }), "Update system");
    printSuccess(`System ${id} updated.`);
  },
};

const deleteCommand: CommandDef = {
  name: "delete",
  description: "Delete a system",
  args: [{ name: "system-id", description: "System ID", required: true }],
  options: {
    force: { type: "boolean", short: "f", description: "Skip confirmation", default: false },
  },
  handler: async (parsed: ParsedArgs) => {
    const id = reqId(parsed);
    if (parsed.values["force"] !== true) {
      printError(`Use --force to confirm deleting system ${id}`);
      throw new CLIError("Confirmation required", 1);
    }
    unwrap(await api.DELETE("/systems/{system_id}", { params: { path: { system_id: id } } }), "Delete system");
    printSuccess(`System ${id} deleted.`);
  },
};

// --- Observability ---

const statusCommand: CommandDef = {
  name: "status",
  description: "Show system health status",
  args: [{ name: "system-id", description: "System ID", required: true }],
  handler: async (parsed: ParsedArgs) => {
    const id = reqId(parsed);
    const d = unwrap(await api.GET("/systems/{system_id}/status", { params: { path: { system_id: id } } }), "Get system status");
    const h = d.overall_status;
    const color = h === "healthy" ? GREEN : h === "degraded" ? YELLOW : RED;

    print(`${style("System Status:", BOLD)} ${d.system_name || id}`);
    print(`  Health:    ${style(h, color)}`);
    print(`  Repos:     ${d.total_repos}`);

    const repos = d.repos ?? [];
    if (repos.length > 0) {
      const table = new Table({ title: "Repository Health" });
      table.addColumn("Repo", { style: CYAN });
      table.addColumn("Health");
      table.addColumn("Last Run");
      table.addColumn("Success Rate", { align: "right" });

      for (const r of repos) {
        const rh = r.status;
        const rc = rh === "healthy" ? GREEN : rh === "degraded" ? YELLOW : RED;
        table.addRow(
          r.repo_full_name || r.repo_id,
          style(rh, rc),
          formatTimestamp(r.last_execution_at || undefined),
          `${(r.success_rate * 100).toFixed(0)}%`,
        );
      }
      table.print();
    }
  },
};

const costCommand: CommandDef = {
  name: "cost",
  description: "Show cost breakdown for a system",
  args: [{ name: "system-id", description: "System ID", required: true }],
  handler: async (parsed: ParsedArgs) => {
    const id = reqId(parsed);
    const d = unwrap(await api.GET("/systems/{system_id}/cost", { params: { path: { system_id: id } } }), "Get system cost");

    print(`${style("System Costs:", BOLD)} ${id}`);
    print(`  Total cost:  ${formatCost(d.total_cost_usd)}`);
    print(`  Tokens:      ${formatTokens(d.total_tokens)}`);

    const byRepo = d.cost_by_repo ?? {};
    const repoEntries = Object.entries(byRepo);
    if (repoEntries.length > 0) {
      const table = new Table({ title: "Cost by Repository" });
      table.addColumn("Repo", { style: CYAN });
      table.addColumn("Cost", { align: "right" });
      for (const [repo, cost] of repoEntries) {
        table.addRow(repo, formatCost(cost));
      }
      table.print();
    }
  },
};

const activityCommand: CommandDef = {
  name: "activity",
  description: "Show recent execution activity for a system",
  args: [{ name: "system-id", description: "System ID", required: true }],
  options: {
    limit: { type: "string", short: "n", description: "Max results", default: "20" },
  },
  handler: async (parsed: ParsedArgs) => {
    const id = reqId(parsed);
    const limit = Number((parsed.values["limit"] as string | undefined) ?? "20");
    const d = unwrap(await api.GET("/systems/{system_id}/activity", { params: { path: { system_id: id }, query: { limit } } }), "Get system activity");
    const items = d.entries ?? [];
    if (items.length === 0) { printDim("No recent activity."); return; }

    const table = new Table({ title: `Activity: ${id}` });
    table.addColumn("Execution", { style: DIM });
    table.addColumn("Workflow");
    table.addColumn("Status");
    table.addColumn("Started");

    for (const e of items) {
      table.addRow(
        e.execution_id.slice(0, 12),
        e.workflow_name,
        formatStatus(e.status),
        formatTimestamp(e.started_at),
      );
    }
    table.print();
  },
};

const patternsCommand: CommandDef = {
  name: "patterns",
  description: "Show failure patterns and cost outliers for a system",
  args: [{ name: "system-id", description: "System ID", required: true }],
  handler: async (parsed: ParsedArgs) => {
    const id = reqId(parsed);
    const d = unwrap(await api.GET("/systems/{system_id}/patterns", { params: { path: { system_id: id } } }), "Get system patterns");

    const failures = d.failure_patterns ?? [];
    if (failures.length > 0) {
      const table = new Table({ title: "Failure Patterns" });
      table.addColumn("Pattern");
      table.addColumn("Count", { align: "right" });
      table.addColumn("Last Seen");
      for (const f of failures) {
        table.addRow(
          f.error_message.slice(0, 60),
          String(f.occurrence_count),
          formatTimestamp(f.last_seen || undefined),
        );
      }
      table.print();
    } else {
      printDim("No failure patterns detected.");
    }

    const outliers = d.cost_outliers ?? [];
    if (outliers.length > 0) {
      const table = new Table({ title: "Cost Outliers" });
      table.addColumn("Execution", { style: DIM });
      table.addColumn("Cost", { align: "right" });
      table.addColumn("Median Cost", { align: "right" });
      table.addColumn("Ratio", { align: "right" });
      for (const o of outliers) {
        table.addRow(
          o.execution_id.slice(0, 12),
          formatCost(o.cost_usd),
          formatCost(o.median_cost_usd),
          `${o.deviation_factor.toFixed(1)}x`,
        );
      }
      table.print();
    }
  },
};

const historyCommand: CommandDef = {
  name: "history",
  description: "Show full execution history for a system",
  args: [{ name: "system-id", description: "System ID", required: true }],
  options: {
    limit: { type: "string", short: "n", description: "Max results", default: "50" },
  },
  handler: async (parsed: ParsedArgs) => {
    const id = reqId(parsed);
    const limit = Number((parsed.values["limit"] as string | undefined) ?? "50");
    const d = unwrap(await api.GET("/systems/{system_id}/history", { params: { path: { system_id: id }, query: { limit } } }), "Get system history");
    const items = d.entries ?? [];
    if (items.length === 0) { printDim("No execution history."); return; }

    const table = new Table({ title: `History: ${id}` });
    table.addColumn("Execution", { style: DIM });
    table.addColumn("Workflow");
    table.addColumn("Status");
    table.addColumn("Started");
    table.addColumn("Duration", { align: "right" });

    for (const e of items) {
      table.addRow(
        e.execution_id.slice(0, 12),
        e.workflow_name,
        formatStatus(e.status),
        formatTimestamp(e.started_at),
        e.duration_seconds ? formatDuration(e.duration_seconds * 1000) : "\u2014",
      );
    }
    table.print();
  },
};

export const systemGroup = new CommandGroup("system", "Manage systems and view system observability");
systemGroup
  .command(createCommand)
  .command(listCommand)
  .command(showCommand)
  .command(updateCommand)
  .command(deleteCommand)
  .command(statusCommand)
  .command(costCommand)
  .command(activityCommand)
  .command(patternsCommand)
  .command(historyCommand);
