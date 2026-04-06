/**
 * Repository management commands — CRUD + observability.
 * Port of apps/syn-cli/src/syn_cli/commands/repo.py
 */

import { CommandGroup, type CommandDef, type ParsedArgs } from "../framework/command.js";
import { CLIError } from "../framework/errors.js";
import { apiGet, apiGetPaginated, apiPost, buildParams } from "../client/api.js";
import { print, printError, printDim, printSuccess } from "../output/console.js";
import { style, BOLD, CYAN, DIM, GREEN, RED, YELLOW } from "../output/ansi.js";
import { formatCost, formatDuration, formatStatus, formatTimestamp, formatTokens } from "../output/format.js";
import { Table } from "../output/table.js";

function reqRepoId(parsed: ParsedArgs): string {
  const id = parsed.positionals[0];
  if (!id) { printError("Missing repo-id"); throw new CLIError("Missing argument", 1); }
  return id;
}

const registerCommand: CommandDef = {
  name: "register",
  description: "Register a repository",
  options: {
    url: { type: "string", short: "u", description: "Repository URL (owner/repo or full URL)" },
    system: { type: "string", short: "s", description: "Assign to system ID" },
    org: { type: "string", short: "o", description: "Organization ID" },
  },
  handler: async (parsed: ParsedArgs) => {
    const url = parsed.values["url"] as string | undefined;
    if (!url) { printError("Missing --url"); throw new CLIError("Missing option", 1); }

    let org = parsed.values["org"] as string | undefined;
    if (!org) {
      // Auto-select if exactly one organization exists
      const orgs = await apiGetPaginated<Record<string, unknown>>("/organizations", "organizations");
      if (orgs.length === 1) {
        const orgId = orgs[0]!["organization_id"];
        if (typeof orgId !== "string" || orgId === "") {
          printError("Organization found but has no valid ID");
          throw new CLIError("Invalid organization data", 1);
        }
        org = orgId;
        printDim(`Using organization: ${org}`);
      } else if (orgs.length === 0) {
        printError("No organizations found. Create one first with: syn org create");
        throw new CLIError("No organizations", 1);
      } else {
        printError("Multiple organizations found. Specify one with --org");
        throw new CLIError("Missing option", 1);
      }
    }

    const body: Record<string, unknown> = { full_name: url, organization_id: org };
    const system = parsed.values["system"] as string | undefined;
    if (system) body["system_id"] = system;

    const d = await apiPost<Record<string, unknown>>("/repos", { body, expected: [200, 201] });
    printSuccess(`Repository registered: ${d["repo_id"] ?? ""}`);
    print(`  Name: ${d["full_name"] ?? url}`);
    if (d["system_id"]) print(`  System: ${String(d["system_id"])}`);
  },
};

const listCommand: CommandDef = {
  name: "list",
  description: "List repositories",
  options: {
    org: { type: "string", short: "o", description: "Filter by organization" },
    system: { type: "string", short: "s", description: "Filter by system" },
  },
  handler: async (parsed: ParsedArgs) => {
    const params = buildParams({
      organization_id: (parsed.values["org"] as string | undefined) ?? null,
      system_id: (parsed.values["system"] as string | undefined) ?? null,
    });
    const items = await apiGetPaginated<Record<string, unknown>>("/repos", "repos", { params });
    if (items.length === 0) { printDim("No repositories found."); return; }

    const table = new Table({ title: "Repositories" });
    table.addColumn("ID", { style: CYAN });
    table.addColumn("Name");
    table.addColumn("System", { style: DIM });

    for (const r of items) {
      table.addRow(
        String(r["repo_id"] ?? ""),
        String(r["full_name"] ?? ""),
        String(r["system_id"] ?? "\u2014"),
      );
    }
    table.print();
  },
};

const showCommand: CommandDef = {
  name: "show",
  description: "Show repository details",
  args: [{ name: "repo-id", description: "Repository ID", required: true }],
  handler: async (parsed: ParsedArgs) => {
    const id = reqRepoId(parsed);
    const d = await apiGet<Record<string, unknown>>(`/repos/${id}`);
    print(`${style("Repository:", BOLD)} ${d["full_name"] ?? id}`);
    print(`  ID:     ${d["repo_id"] ?? id}`);
    if (d["system_id"]) print(`  System: ${String(d["system_id"])}`);
    if (d["organization_id"]) print(`  Org:    ${String(d["organization_id"])}`);
  },
};

const assignCommand: CommandDef = {
  name: "assign",
  description: "Assign a repository to a system",
  args: [{ name: "repo-id", description: "Repository ID", required: true }],
  options: {
    system: { type: "string", short: "s", description: "System ID to assign to" },
  },
  handler: async (parsed: ParsedArgs) => {
    const id = reqRepoId(parsed);
    const system = parsed.values["system"] as string | undefined;
    if (!system) { printError("Missing --system"); throw new CLIError("Missing option", 1); }
    await apiPost(`/repos/${id}/assign`, { body: { system_id: system } });
    printSuccess(`Repository ${id} assigned to system ${system}.`);
  },
};

const unassignCommand: CommandDef = {
  name: "unassign",
  description: "Remove repository from its system",
  args: [{ name: "repo-id", description: "Repository ID", required: true }],
  handler: async (parsed: ParsedArgs) => {
    const id = reqRepoId(parsed);
    await apiPost(`/repos/${id}/unassign`);
    printSuccess(`Repository ${id} unassigned from system.`);
  },
};

const healthCommand: CommandDef = {
  name: "health",
  description: "Show health metrics for a repository",
  args: [{ name: "repo-id", description: "Repository ID", required: true }],
  handler: async (parsed: ParsedArgs) => {
    const id = reqRepoId(parsed);
    const d = await apiGet<Record<string, unknown>>(`/repos/${id}/health`);
    const h = String(d["health_status"] ?? "unknown");
    const color = h === "healthy" ? GREEN : h === "degraded" ? YELLOW : RED;

    print(`${style("Repository Health:", BOLD)} ${id}`);
    print(`  Status:          ${style(h, color)}`);
    print(`  Success rate:    ${d["success_rate"] != null ? `${(Number(d["success_rate"]) * 100).toFixed(1)}%` : "\u2014"}`);
    print(`  Avg duration:    ${d["avg_duration_ms"] != null ? formatDuration(Number(d["avg_duration_ms"])) : "\u2014"}`);
    print(`  Total runs:      ${d["total_executions"] ?? 0}`);

    const trends = (d["trends"] ?? []) as Record<string, unknown>[];
    if (trends.length > 0) {
      const table = new Table({ title: "Trends" });
      table.addColumn("Period");
      table.addColumn("Runs", { align: "right" });
      table.addColumn("Success", { align: "right" });
      table.addColumn("Cost", { align: "right" });
      for (const t of trends) {
        table.addRow(
          String(t["period"] ?? ""),
          String(t["count"] ?? 0),
          String(t["success_count"] ?? 0),
          formatCost(String(t["cost_usd"] ?? "0")),
        );
      }
      table.print();
    }
  },
};

const costCommand: CommandDef = {
  name: "cost",
  description: "Show cost breakdown for a repository",
  args: [{ name: "repo-id", description: "Repository ID", required: true }],
  handler: async (parsed: ParsedArgs) => {
    const id = reqRepoId(parsed);
    const d = await apiGet<Record<string, unknown>>(`/repos/${id}/cost`);

    print(`${style("Repository Costs:", BOLD)} ${id}`);
    print(`  Total cost:  ${formatCost(String(d["total_cost_usd"] ?? "0"))}`);
    print(`  Tokens:      ${formatTokens(Number(d["total_tokens"] ?? 0))}`);

    const byModel = (d["by_model"] ?? []) as Record<string, unknown>[];
    if (byModel.length > 0) {
      const table = new Table({ title: "Cost by Model" });
      table.addColumn("Model", { style: CYAN });
      table.addColumn("Cost", { align: "right" });
      table.addColumn("Tokens", { align: "right" });
      for (const m of byModel) {
        table.addRow(
          String(m["model"] ?? ""),
          formatCost(String(m["cost_usd"] ?? "0")),
          formatTokens(Number(m["tokens"] ?? 0)),
        );
      }
      table.print();
    }
  },
};

const activityCommand: CommandDef = {
  name: "activity",
  description: "Show recent execution activity for a repository",
  args: [{ name: "repo-id", description: "Repository ID", required: true }],
  options: {
    limit: { type: "string", short: "n", description: "Max results", default: "20" },
  },
  handler: async (parsed: ParsedArgs) => {
    const id = reqRepoId(parsed);
    const limit = (parsed.values["limit"] as string | undefined) ?? "20";
    const items = await apiGetPaginated<Record<string, unknown>>(`/repos/${id}/activity`, "entries", { params: { limit } });
    if (items.length === 0) { printDim("No recent activity."); return; }

    const table = new Table({ title: `Activity: ${id}` });
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

const failuresCommand: CommandDef = {
  name: "failures",
  description: "Show recent execution failures for a repository",
  args: [{ name: "repo-id", description: "Repository ID", required: true }],
  options: {
    limit: { type: "string", short: "n", description: "Max results", default: "10" },
  },
  handler: async (parsed: ParsedArgs) => {
    const id = reqRepoId(parsed);
    const limit = (parsed.values["limit"] as string | undefined) ?? "10";
    const items = await apiGetPaginated<Record<string, unknown>>(`/repos/${id}/failures`, "failures", { params: { limit } });
    if (items.length === 0) { printDim("No recent failures."); return; }

    const table = new Table({ title: `Failures: ${id}` });
    table.addColumn("Execution", { style: DIM });
    table.addColumn("Workflow");
    table.addColumn("Error");
    table.addColumn("Time");

    for (const e of items) {
      table.addRow(
        String(e["execution_id"] ?? "").slice(0, 12),
        String(e["workflow_name"] ?? ""),
        String(e["error_message"] ?? "\u2014").slice(0, 60),
        formatTimestamp(e["failed_at"] as string | undefined),
      );
    }
    table.print();
  },
};

const sessionsCommand: CommandDef = {
  name: "sessions",
  description: "Show agent sessions for a repository",
  args: [{ name: "repo-id", description: "Repository ID", required: true }],
  options: {
    limit: { type: "string", short: "n", description: "Max results", default: "20" },
  },
  handler: async (parsed: ParsedArgs) => {
    const id = reqRepoId(parsed);
    const limit = (parsed.values["limit"] as string | undefined) ?? "20";
    const items = await apiGetPaginated<Record<string, unknown>>(`/repos/${id}/sessions`, "sessions", { params: { limit } });
    if (items.length === 0) { printDim("No sessions found."); return; }

    const table = new Table({ title: `Sessions: ${id}` });
    table.addColumn("Session", { style: DIM });
    table.addColumn("Status");
    table.addColumn("Started");
    table.addColumn("Tokens", { align: "right" });
    table.addColumn("Cost", { align: "right" });

    for (const s of items) {
      table.addRow(
        String(s["session_id"] ?? "").slice(0, 12),
        formatStatus(String(s["status"] ?? "")),
        formatTimestamp(s["started_at"] as string | undefined),
        formatTokens(Number(s["total_tokens"] ?? 0)),
        formatCost(String(s["cost_usd"] ?? "0")),
      );
    }
    table.print();
  },
};

export const repoGroup = new CommandGroup("repo", "Manage repositories and view observability data");
repoGroup
  .command(registerCommand)
  .command(listCommand)
  .command(showCommand)
  .command(assignCommand)
  .command(unassignCommand)
  .command(healthCommand)
  .command(costCommand)
  .command(activityCommand)
  .command(failuresCommand)
  .command(sessionsCommand);
