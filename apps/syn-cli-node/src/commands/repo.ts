/**
 * Repository management commands — CRUD + observability.
 * Port of apps/syn-cli/src/syn_cli/commands/repo.py
 */

import { CommandGroup, type CommandDef, type ParsedArgs } from "../framework/command.js";
import { CLIError } from "../framework/errors.js";
import { api, unwrap } from "../client/typed.js";
import { print, printError, printDim, printSuccess } from "../output/console.js";
import { style, BOLD, CYAN, DIM } from "../output/ansi.js";
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
      const orgsData = unwrap(await api.GET("/organizations"), "List organizations");
      const orgs = orgsData.organizations ?? [];
      if (orgs.length === 1) {
        org = orgs[0]!.organization_id;
        if (!org) {
          printError("Organization ID missing from API response");
          throw new CLIError("Invalid organization data", 1);
        }
        printDim(`Using organization: ${org}`);
      } else if (orgs.length === 0) {
        printError("No organizations found. Create one first with: syn org create");
        throw new CLIError("No organizations", 1);
      } else {
        printError("Multiple organizations found. Specify one with --org");
        throw new CLIError("Missing option", 1);
      }
    }

    const body = {
      full_name: url,
      organization_id: org,
      provider: "github",
      owner: "",
      default_branch: "main",
      provider_repo_id: "",
      installation_id: "",
      is_private: false,
      created_by: "cli",
    };

    const d = unwrap(await api.POST("/repos", { body }), "Register repository");
    printSuccess(`Repository registered: ${d.repo_id}`);
    print(`  Name: ${d.full_name}`);
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
    const d = unwrap(await api.GET("/repos", {
      params: {
        query: {
          organization_id: (parsed.values["org"] as string | undefined) ?? null,
          system_id: (parsed.values["system"] as string | undefined) ?? null,
        },
      },
    }), "List repositories");
    const items = d.repos ?? [];
    if (items.length === 0) { printDim("No repositories found."); return; }

    const table = new Table({ title: "Repositories" });
    table.addColumn("ID", { style: CYAN });
    table.addColumn("Name");
    table.addColumn("System", { style: DIM });

    for (const r of items) {
      table.addRow(
        r.repo_id,
        r.full_name,
        r.system_id || "\u2014",
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
    const d = unwrap(await api.GET("/repos/{repo_id}", { params: { path: { repo_id: id } } }), "Get repository");
    print(`${style("Repository:", BOLD)} ${d.full_name}`);
    print(`  ID:     ${d.repo_id}`);
    if (d.system_id) print(`  System: ${d.system_id}`);
    if (d.organization_id) print(`  Org:    ${d.organization_id}`);
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
    unwrap(await api.POST("/repos/{repo_id}/assign", { params: { path: { repo_id: id } }, body: { system_id: system } }), "Assign repository");
    printSuccess(`Repository ${id} assigned to system ${system}.`);
  },
};

const unassignCommand: CommandDef = {
  name: "unassign",
  description: "Remove repository from its system",
  args: [{ name: "repo-id", description: "Repository ID", required: true }],
  handler: async (parsed: ParsedArgs) => {
    const id = reqRepoId(parsed);
    unwrap(await api.POST("/repos/{repo_id}/unassign", { params: { path: { repo_id: id } } }), "Unassign repository");
    printSuccess(`Repository ${id} unassigned from system.`);
  },
};

const healthCommand: CommandDef = {
  name: "health",
  description: "Show health metrics for a repository",
  args: [{ name: "repo-id", description: "Repository ID", required: true }],
  handler: async (parsed: ParsedArgs) => {
    const id = reqRepoId(parsed);
    const d = unwrap(await api.GET("/repos/{repo_id}/health", { params: { path: { repo_id: id } } }), "Get repo health");

    print(`${style("Repository Health:", BOLD)} ${id}`);
    print(`  Success rate:    ${(d.success_rate * 100).toFixed(1)}%`);
    print(`  Trend:           ${d.trend}`);
    print(`  Total runs:      ${d.total_executions}`);
    print(`  Window cost:     ${formatCost(d.window_cost_usd)}`);
    print(`  Window tokens:   ${formatTokens(d.window_tokens)}`);
    if (d.last_execution_at) print(`  Last execution:  ${formatTimestamp(d.last_execution_at)}`);
  },
};

const costCommand: CommandDef = {
  name: "cost",
  description: "Show cost breakdown for a repository",
  args: [{ name: "repo-id", description: "Repository ID", required: true }],
  handler: async (parsed: ParsedArgs) => {
    const id = reqRepoId(parsed);
    const d = unwrap(await api.GET("/repos/{repo_id}/cost", { params: { path: { repo_id: id } } }), "Get repo cost");

    print(`${style("Repository Costs:", BOLD)} ${id}`);
    print(`  Total cost:  ${formatCost(d.total_cost_usd)}`);
    print(`  Tokens:      ${formatTokens(d.total_tokens)}`);

    const byModel = d.cost_by_model ?? {};
    const modelEntries = Object.entries(byModel);
    if (modelEntries.length > 0) {
      const table = new Table({ title: "Cost by Model" });
      table.addColumn("Model", { style: CYAN });
      table.addColumn("Cost", { align: "right" });
      for (const [model, cost] of modelEntries) {
        table.addRow(model, formatCost(cost));
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
    const limit = Number((parsed.values["limit"] as string | undefined) ?? "20");
    const d = unwrap(await api.GET("/repos/{repo_id}/activity", { params: { path: { repo_id: id }, query: { limit } } }), "Get repo activity");
    const items = d.entries ?? [];
    if (items.length === 0) { printDim("No recent activity."); return; }

    const table = new Table({ title: `Activity: ${id}` });
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

const failuresCommand: CommandDef = {
  name: "failures",
  description: "Show recent execution failures for a repository",
  args: [{ name: "repo-id", description: "Repository ID", required: true }],
  options: {
    limit: { type: "string", short: "n", description: "Max results", default: "10" },
  },
  handler: async (parsed: ParsedArgs) => {
    const id = reqRepoId(parsed);
    const limit = Number((parsed.values["limit"] as string | undefined) ?? "10");
    const d = unwrap(await api.GET("/repos/{repo_id}/failures", { params: { path: { repo_id: id }, query: { limit } } }), "Get repo failures");
    const items = d.failures ?? [];
    if (items.length === 0) { printDim("No recent failures."); return; }

    const table = new Table({ title: `Failures: ${id}` });
    table.addColumn("Execution", { style: DIM });
    table.addColumn("Workflow");
    table.addColumn("Error");
    table.addColumn("Time");

    for (const e of items) {
      table.addRow(
        e.execution_id.slice(0, 12),
        e.workflow_name,
        e.error_message.slice(0, 60) || "\u2014",
        formatTimestamp(e.failed_at),
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
    const limit = Number((parsed.values["limit"] as string | undefined) ?? "20");
    const d = unwrap(await api.GET("/repos/{repo_id}/sessions", { params: { path: { repo_id: id }, query: { limit } } }), "Get repo sessions");
    const items = d.sessions ?? [];
    if (items.length === 0) { printDim("No sessions found."); return; }

    const table = new Table({ title: `Sessions: ${id}` });
    table.addColumn("Session", { style: DIM });
    table.addColumn("Status");
    table.addColumn("Started");
    table.addColumn("Tokens", { align: "right" });
    table.addColumn("Cost", { align: "right" });

    for (const s of items) {
      table.addRow(
        s.id.slice(0, 12),
        formatStatus(s.status),
        formatTimestamp(s.started_at),
        formatTokens(s.total_tokens),
        formatCost(s.total_cost_usd),
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
