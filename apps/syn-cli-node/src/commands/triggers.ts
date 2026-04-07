/**
 * Trigger management commands — register, enable, list, show, history, pause, resume, delete, disable.
 * Port of apps/syn-cli/src/syn_cli/commands/triggers.py
 */

import { CommandGroup, type CommandDef, type ParsedArgs } from "../framework/command.js";
import { CLIError } from "../framework/errors.js";
import { api, unwrap } from "../client/typed.js";
import type { components } from "../generated/api-types.js";
import { print, printError, printDim, printSuccess } from "../output/console.js";
import { style, BOLD, CYAN, DIM } from "../output/ansi.js";
import { formatCost, formatStatus, formatTimestamp } from "../output/format.js";
import { Table } from "../output/table.js";

type TriggerDetail = components["schemas"]["TriggerDetail"];
type TriggerSummary = components["schemas"]["TriggerSummary"];
type TriggerHistoryEntry = components["schemas"]["TriggerHistoryEntryResponse"];

function reqId(parsed: ParsedArgs): string {
  const id = parsed.positionals[0];
  if (!id) { printError("Missing trigger-id"); throw new CLIError("Missing argument", 1); }
  return id;
}

function parseConditions(condStrs: string[]): Record<string, string>[] {
  return condStrs.map((c) => {
    const eqIdx = c.indexOf("=");
    if (eqIdx < 1) throw new CLIError(`Invalid condition format: ${c} (expected field=value)`, 1);
    return { field: c.slice(0, eqIdx), operator: "eq", value: c.slice(eqIdx + 1) };
  });
}

const registerCommand: CommandDef = {
  name: "register",
  description: "Register a new trigger rule",
  options: {
    repo: { type: "string", short: "r", description: "Repository ID" },
    workflow: { type: "string", short: "w", description: "Workflow ID to execute" },
    event: { type: "string", short: "e", description: "GitHub event type (e.g. check_run.completed)" },
    condition: { type: "string", short: "c", multiple: true, description: "Condition as field=value (repeatable, uses 'eq' operator)" },
    "max-fires": { type: "string", description: "Maximum fire attempts per PR/trigger combination", default: "5" },
    cooldown: { type: "string", description: "Cooldown in seconds", default: "300" },
  },
  handler: async (parsed: ParsedArgs) => {
    const repo = parsed.values["repo"] as string | undefined;
    const workflow = parsed.values["workflow"] as string | undefined;
    const event = parsed.values["event"] as string | undefined;
    if (!repo) { printError("Missing --repo"); throw new CLIError("Missing option", 1); }
    if (!workflow) { printError("Missing --workflow"); throw new CLIError("Missing option", 1); }
    if (!event) { printError("Missing --event"); throw new CLIError("Missing option", 1); }

    const conditionStrs = (parsed.values["condition"] as string[] | undefined) ?? [];
    const conditions = conditionStrs.length > 0 ? parseConditions(conditionStrs) : [];

    const config: Record<string, unknown> = {
      max_attempts: parseInt((parsed.values["max-fires"] as string | undefined) ?? "5", 10),
      cooldown_seconds: parseInt((parsed.values["cooldown"] as string | undefined) ?? "300", 10),
    };

    const d = unwrap(await api.POST("/triggers", {
      body: {
        name: `${event} → ${workflow}`,
        repository: repo,
        workflow_id: workflow,
        event,
        conditions,
        config,
        installation_id: "",
        created_by: "cli",
      },
    }), "Register trigger");
    printSuccess(`Trigger registered: ${d.trigger_id}`);
  },
};

const enablePresetCommand: CommandDef = {
  name: "enable",
  description: "Enable a built-in trigger preset",
  args: [{ name: "preset", description: "Preset name (self-healing, review-fix, comment-command)", required: true }],
  options: {
    repo: { type: "string", short: "r", description: "Repository ID" },
    workflow: { type: "string", short: "w", description: "Workflow ID to dispatch (default: preset default)" },
  },
  handler: async (parsed: ParsedArgs) => {
    const preset = parsed.positionals[0];
    if (!preset) { printError("Missing preset name"); throw new CLIError("Missing argument", 1); }
    const repo = parsed.values["repo"] as string | undefined;
    if (!repo) { printError("Missing --repo"); throw new CLIError("Missing option", 1); }
    const workflow = parsed.values["workflow"] as string | undefined;

    const d = unwrap(
      await api.POST("/triggers/presets/{preset_name}", {
        params: { path: { preset_name: preset } },
        body: { repository: repo, installation_id: "", created_by: "cli", workflow_id: workflow ?? "" },
      }),
      "Enable preset",
    );
    printSuccess(`Preset "${preset}" enabled: ${d.trigger_id}`);
  },
};

const listCommand: CommandDef = {
  name: "list",
  description: "List trigger rules",
  options: {
    repo: { type: "string", short: "r", description: "Filter by repository" },
    status: { type: "string", short: "s", description: "Filter by status (active, paused, deleted)" },
    all: { type: "boolean", short: "a", description: "Include deleted triggers", default: false },
  },
  handler: async (parsed: ParsedArgs) => {
    const showAll = parsed.values["all"] === true;
    const explicitStatus = (parsed.values["status"] as string | undefined) ?? null;

    const d = unwrap(
      await api.GET("/triggers", {
        params: { query: {
          repository: (parsed.values["repo"] as string | undefined) ?? null,
          status: explicitStatus,
        }},
      }),
      "List triggers",
    );

    let items: TriggerSummary[] = d.triggers ?? [];
    // Hide deleted triggers by default unless --all or explicit --status is set
    if (!showAll && !explicitStatus) {
      items = items.filter((t) => t.status !== "deleted");
    }
    if (items.length === 0) { printDim("No triggers found."); return; }

    const table = new Table({ title: "Triggers" });
    table.addColumn("ID", { style: CYAN });
    table.addColumn("Event");
    table.addColumn("Repo", { style: DIM });
    table.addColumn("Workflow", { style: DIM });
    table.addColumn("Status");
    table.addColumn("Fires", { align: "right" });

    for (const t of items) {
      table.addRow(
        t.trigger_id.slice(0, 12),
        t.event,
        t.repository.slice(0, 12),
        t.workflow_id.slice(0, 12),
        formatStatus(t.status),
        String(t.fire_count),
      );
    }
    table.print();
  },
};

function renderTriggerDetail(d: TriggerDetail, fallbackId?: string): void {
  print(`${style("Trigger:", BOLD)} ${d.trigger_id || fallbackId || ""}`);
  print(`  Event:      ${d.event}`);
  print(`  Repo:       ${d.repository}`);
  print(`  Workflow:   ${d.workflow_id}`);
  print(`  Status:     ${formatStatus(d.status)}`);
  print(`  Fires:      ${d.fire_count} / max —`);
  if (d.last_fired_at) print(`  Last fired: ${formatTimestamp(d.last_fired_at)}`);

  const conditions = d.conditions ?? [];
  if (conditions.length > 0) {
    print(style("  Conditions:", BOLD));
    for (const c of conditions) {
      print(`    ${c["field"] ?? ""} = ${c["value"] ?? ""}`);
    }
  }
}

const showCommand: CommandDef = {
  name: "show",
  description: "Show trigger details",
  args: [{ name: "trigger-id", description: "Trigger ID", required: true }],
  handler: async (parsed: ParsedArgs) => {
    const id = reqId(parsed);
    const d = unwrap(
      await api.GET("/triggers/{trigger_id}", { params: { path: { trigger_id: id } } }),
      "Get trigger",
    );
    renderTriggerDetail(d, id);
  },
};

const historyCommand: CommandDef = {
  name: "history",
  description: "Show trigger execution history",
  args: [{ name: "trigger-id", description: "Trigger ID", required: true }],
  options: {
    limit: { type: "string", short: "n", description: "Max results", default: "20" },
  },
  handler: async (parsed: ParsedArgs) => {
    const id = reqId(parsed);
    const limit = parseInt((parsed.values["limit"] as string | undefined) ?? "20", 10);
    const d = unwrap(
      await api.GET("/triggers/{trigger_id}/history", {
        params: { path: { trigger_id: id }, query: { limit } },
      }),
      "Get trigger history",
    );

    const items: TriggerHistoryEntry[] = d.entries ?? [];
    if (items.length === 0) { printDim("No trigger history."); return; }

    const hasBlocked = items.some((h) => h.status === "blocked");

    const table = new Table({ title: `Trigger History: ${id.slice(0, 12)}` });
    table.addColumn("Time");
    table.addColumn("Execution", { style: DIM });
    table.addColumn("Status");
    table.addColumn("Cost", { align: "right" });
    if (hasBlocked) {
      table.addColumn("Guard");
      table.addColumn("Reason");
    }

    for (const h of items) {
      const status = h.status;
      const baseColumns = [
        formatTimestamp(h.fired_at ?? undefined),
        status === "blocked" ? "—" : h.execution_id.slice(0, 12),
        formatStatus(status),
        status === "blocked" ? "—" : formatCost(String(h.cost_usd ?? "0")),
      ];
      if (hasBlocked) {
        baseColumns.push(
          status === "blocked" ? h.guard_name : "—",
          status === "blocked" ? h.block_reason : "—",
        );
      }
      table.addRow(...baseColumns);
    }
    table.print();
  },
};

const pauseCommand: CommandDef = {
  name: "pause",
  description: "Pause a trigger rule",
  args: [{ name: "trigger-id", description: "Trigger ID", required: true }],
  handler: async (parsed: ParsedArgs) => {
    const id = reqId(parsed);
    unwrap(
      await api.PATCH("/triggers/{trigger_id}", {
        params: { path: { trigger_id: id } },
        body: { action: "pause", paused_by: "cli", resumed_by: "" },
      }),
      "Pause trigger",
    );
    printSuccess(`Trigger ${id} paused.`);
  },
};

const resumeCommand: CommandDef = {
  name: "resume",
  description: "Resume a paused trigger rule",
  args: [{ name: "trigger-id", description: "Trigger ID", required: true }],
  handler: async (parsed: ParsedArgs) => {
    const id = reqId(parsed);
    unwrap(
      await api.PATCH("/triggers/{trigger_id}", {
        params: { path: { trigger_id: id } },
        body: { action: "resume", paused_by: "", resumed_by: "cli" },
      }),
      "Resume trigger",
    );
    printSuccess(`Trigger ${id} resumed.`);
  },
};

const deleteCommand: CommandDef = {
  name: "delete",
  description: "Delete a trigger rule",
  args: [{ name: "trigger-id", description: "Trigger ID", required: true }],
  options: {
    force: { type: "boolean", short: "f", description: "Skip confirmation", default: false },
  },
  handler: async (parsed: ParsedArgs) => {
    const id = reqId(parsed);
    if (parsed.values["force"] !== true) {
      printError(`Use --force to confirm deleting trigger ${id}`);
      throw new CLIError("Confirmation required", 1);
    }
    unwrap(
      await api.DELETE("/triggers/{trigger_id}", { params: { path: { trigger_id: id } } }),
      "Delete trigger",
    );
    printSuccess(`Trigger ${id} deleted.`);
  },
};

const disableAllCommand: CommandDef = {
  name: "disable-all",
  description: "Disable all triggers for a repository",
  options: {
    repo: { type: "string", short: "r", description: "Repository ID" },
    force: { type: "boolean", short: "f", description: "Skip confirmation", default: false },
  },
  handler: async (parsed: ParsedArgs) => {
    const repo = parsed.values["repo"] as string | undefined;
    if (!repo) { printError("Missing --repo"); throw new CLIError("Missing option", 1); }
    if (parsed.values["force"] !== true) {
      printError(`Use --force to confirm disabling all triggers for repo ${repo}`);
      throw new CLIError("Confirmation required", 1);
    }
    const d = unwrap(
      await api.GET("/triggers", {
        params: { query: { repository: repo, status: "active" } },
      }),
      "List active triggers",
    );
    const triggers = d.triggers ?? [];
    if (triggers.length === 0) { printDim("No active triggers found."); return; }
    let count = 0;
    for (const t of triggers) {
      if (t.trigger_id) {
        await api.PATCH("/triggers/{trigger_id}", {
          params: { path: { trigger_id: t.trigger_id } },
          body: { action: "pause", paused_by: "cli", resumed_by: "" },
        });
        count++;
      }
    }
    printSuccess(`Disabled ${count} trigger(s) for repository ${repo}.`);
  },
};

export const triggersGroup = new CommandGroup("triggers", "Manage self-healing trigger rules");
triggersGroup
  .command(registerCommand)
  .command(enablePresetCommand)
  .command(listCommand)
  .command(showCommand)
  .command(historyCommand)
  .command(pauseCommand)
  .command(resumeCommand)
  .command(deleteCommand)
  .command(disableAllCommand);
