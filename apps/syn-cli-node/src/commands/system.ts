/**
 * System management commands — CRUD + observability.
 * Port of apps/syn-cli/src/syn_cli/commands/system/_crud.py + _observability.py
 */

import { CommandGroup, type CommandDef, type ParsedArgs } from "../framework/command.js";
import { CLIError } from "../framework/errors.js";
import { apiGet, apiGetPaginated, apiPost, apiPut, apiDelete, buildParams } from "../client/api.js";
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

    const body: Record<string, unknown> = { name };
    const desc = parsed.values["description"] as string | undefined;
    const org = parsed.values["org"] as string | undefined;
    if (desc) body["description"] = desc;
    if (org) body["organization_id"] = org;

    const d = await apiPost<Record<string, unknown>>("/systems", { body, expected: [200, 201] });
    printSuccess(`System created: ${d["system_id"] ?? ""}`);
    print(`  Name: ${d["name"] ?? name}`);
  },
};

const listCommand: CommandDef = {
  name: "list",
  description: "List all systems",
  options: {
    org: { type: "string", short: "o", description: "Filter by organization" },
  },
  handler: async (parsed: ParsedArgs) => {
    const params = buildParams({
      organization_id: (parsed.values["org"] as string | undefined) ?? null,
    });
    const items = await apiGetPaginated<Record<string, unknown>>("/systems", "systems", { params });
    if (items.length === 0) { printDim("No systems found."); return; }

    const table = new Table({ title: "Systems" });
    table.addColumn("ID", { style: CYAN });
    table.addColumn("Name");
    table.addColumn("Org", { style: DIM });
    table.addColumn("Repos", { align: "right" });
    table.addColumn("Status");

    for (const s of items) {
      table.addRow(
        String(s["system_id"] ?? ""),
        String(s["name"] ?? ""),
        String(s["organization_id"] ?? "\u2014"),
        String(s["repo_count"] ?? 0),
        formatStatus(String(s["status"] ?? "")),
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
    const d = await apiGet<Record<string, unknown>>(`/systems/${id}`);
    print(`${style("System:", BOLD)} ${d["name"] ?? id}`);
    print(`  ID:          ${d["system_id"] ?? id}`);
    if (d["description"]) print(`  Description: ${String(d["description"])}`);
    if (d["organization_id"]) print(`  Org:         ${String(d["organization_id"])}`);
    print(`  Repos:       ${d["repo_count"] ?? 0}`);
    print(`  Status:      ${formatStatus(String(d["status"] ?? ""))}`);
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
    const body: Record<string, unknown> = {};
    const name = parsed.values["name"] as string | undefined;
    const desc = parsed.values["description"] as string | undefined;
    if (name) body["name"] = name;
    if (desc) body["description"] = desc;
    if (Object.keys(body).length === 0) { printError("Nothing to update. Use --name or --description."); throw new CLIError("No updates", 1); }

    await apiPut(`/systems/${id}`, { body });
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
    await apiDelete(`/systems/${id}`);
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
    const d = await apiGet<Record<string, unknown>>(`/systems/${id}/status`);
    const h = String(d["health_status"] ?? "unknown");
    const color = h === "healthy" ? GREEN : h === "degraded" ? YELLOW : RED;

    print(`${style("System Status:", BOLD)} ${d["name"] ?? id}`);
    print(`  Health:    ${style(h, color)}`);
    print(`  Repos:     ${d["repo_count"] ?? 0}`);
    print(`  Active:    ${d["active_executions"] ?? 0}`);

    const repos = (d["repos"] ?? []) as Record<string, unknown>[];
    if (repos.length > 0) {
      const table = new Table({ title: "Repository Health" });
      table.addColumn("Repo", { style: CYAN });
      table.addColumn("Health");
      table.addColumn("Last Run");
      table.addColumn("Success Rate", { align: "right" });

      for (const r of repos) {
        const rh = String(r["health"] ?? "unknown");
        const rc = rh === "healthy" ? GREEN : rh === "degraded" ? YELLOW : RED;
        table.addRow(
          String(r["repo_url"] ?? r["repo_id"] ?? ""),
          style(rh, rc),
          formatTimestamp(r["last_run_at"] as string | undefined),
          r["success_rate"] != null ? `${(Number(r["success_rate"]) * 100).toFixed(0)}%` : "\u2014",
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
    const d = await apiGet<Record<string, unknown>>(`/systems/${id}/costs`);

    print(`${style("System Costs:", BOLD)} ${id}`);
    print(`  Total cost:  ${formatCost(String(d["total_cost_usd"] ?? "0"))}`);
    print(`  Tokens:      ${formatTokens(Number(d["total_tokens"] ?? 0))}`);

    const byRepo = (d["by_repo"] ?? []) as Record<string, unknown>[];
    if (byRepo.length > 0) {
      const table = new Table({ title: "Cost by Repository" });
      table.addColumn("Repo", { style: CYAN });
      table.addColumn("Cost", { align: "right" });
      table.addColumn("Tokens", { align: "right" });
      for (const r of byRepo) {
        table.addRow(
          String(r["repo_url"] ?? r["repo_id"] ?? ""),
          formatCost(String(r["cost_usd"] ?? "0")),
          formatTokens(Number(r["tokens"] ?? 0)),
        );
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
    const limit = (parsed.values["limit"] as string | undefined) ?? "20";
    const items = await apiGetPaginated<Record<string, unknown>>(`/systems/${id}/activity`, "entries", { params: { limit } });
    if (items.length === 0) { printDim("No recent activity."); return; }

    const table = new Table({ title: `Activity: ${id}` });
    table.addColumn("Execution", { style: DIM });
    table.addColumn("Repo");
    table.addColumn("Workflow");
    table.addColumn("Status");
    table.addColumn("Started");
    table.addColumn("Cost", { align: "right" });

    for (const e of items) {
      table.addRow(
        String(e["execution_id"] ?? "").slice(0, 12),
        String(e["repo_url"] ?? ""),
        String(e["workflow_name"] ?? ""),
        formatStatus(String(e["status"] ?? "")),
        formatTimestamp(e["started_at"] as string | undefined),
        formatCost(String(e["cost_usd"] ?? "0")),
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
    const d = await apiGet<Record<string, unknown>>(`/systems/${id}/patterns`);

    const failures = (d["failure_patterns"] ?? []) as Record<string, unknown>[];
    if (failures.length > 0) {
      const table = new Table({ title: "Failure Patterns" });
      table.addColumn("Pattern");
      table.addColumn("Count", { align: "right" });
      table.addColumn("Last Seen");
      for (const f of failures) {
        table.addRow(
          String(f["pattern"] ?? "").slice(0, 60),
          String(f["count"] ?? 0),
          formatTimestamp(f["last_seen"] as string | undefined),
        );
      }
      table.print();
    } else {
      printDim("No failure patterns detected.");
    }

    const outliers = (d["cost_outliers"] ?? []) as Record<string, unknown>[];
    if (outliers.length > 0) {
      const table = new Table({ title: "Cost Outliers" });
      table.addColumn("Execution", { style: DIM });
      table.addColumn("Cost", { align: "right" });
      table.addColumn("Avg Cost", { align: "right" });
      table.addColumn("Ratio", { align: "right" });
      for (const o of outliers) {
        table.addRow(
          String(o["execution_id"] ?? "").slice(0, 12),
          formatCost(String(o["cost_usd"] ?? "0")),
          formatCost(String(o["avg_cost_usd"] ?? "0")),
          `${Number(o["ratio"] ?? 0).toFixed(1)}x`,
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
    status: { type: "string", short: "s", description: "Filter by status" },
  },
  handler: async (parsed: ParsedArgs) => {
    const id = reqId(parsed);
    const params = buildParams({
      limit: (parsed.values["limit"] as string | undefined) ?? "50",
      status: (parsed.values["status"] as string | undefined) ?? null,
    });
    const items = await apiGetPaginated<Record<string, unknown>>(`/systems/${id}/history`, "entries", { params });
    if (items.length === 0) { printDim("No execution history."); return; }

    const table = new Table({ title: `History: ${id}` });
    table.addColumn("Execution", { style: DIM });
    table.addColumn("Workflow");
    table.addColumn("Status");
    table.addColumn("Started");
    table.addColumn("Duration", { align: "right" });
    table.addColumn("Cost", { align: "right" });

    for (const e of items) {
      table.addRow(
        String(e["execution_id"] ?? "").slice(0, 12),
        String(e["workflow_name"] ?? ""),
        formatStatus(String(e["status"] ?? "")),
        formatTimestamp(e["started_at"] as string | undefined),
        e["duration_ms"] != null ? formatDuration(Number(e["duration_ms"])) : "\u2014",
        formatCost(String(e["cost_usd"] ?? "0")),
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
