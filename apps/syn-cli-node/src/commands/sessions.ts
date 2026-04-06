/**
 * Session management commands — list, show.
 * Port of apps/syn-cli/src/syn_cli/commands/sessions.py
 */

import { CommandGroup, type CommandDef, type ParsedArgs } from "../framework/command.js";
import { CLIError } from "../framework/errors.js";
import { apiGet, apiGetPaginated, buildParams } from "../client/api.js";
import { print, printError, printDim } from "../output/console.js";
import { style, BOLD, CYAN, DIM } from "../output/ansi.js";
import { formatCost, formatDuration, formatStatus, formatTimestamp, formatTokens } from "../output/format.js";
import { Table } from "../output/table.js";
import type { SessionSummaryResponse, SessionResponse } from "../generated/types.js";

const listCommand: CommandDef = {
  name: "list",
  description: "List agent sessions",
  options: {
    workflow: { type: "string", short: "w", description: "Filter by workflow ID" },
    status: { type: "string", short: "s", description: "Filter by status" },
    limit: { type: "string", short: "n", description: "Max results", default: "50" },
  },
  handler: async (parsed: ParsedArgs) => {
    const params = buildParams({
      workflow_id: (parsed.values["workflow"] as string | undefined) ?? null,
      status: (parsed.values["status"] as string | undefined) ?? null,
      limit: (parsed.values["limit"] as string | undefined) ?? "50",
    });
    const items = await apiGetPaginated<SessionSummaryResponse>("/sessions", "sessions", { params });
    if (items.length === 0) { printDim("No sessions found."); return; }

    const table = new Table({ title: "Sessions" });
    table.addColumn("Session ID", { style: CYAN });
    table.addColumn("Status");
    table.addColumn("Provider");
    table.addColumn("Started");
    table.addColumn("Tokens", { align: "right" });
    table.addColumn("Cost", { align: "right" });

    for (const s of items) {
      table.addRow(
        s.id.slice(0, 16),
        formatStatus(s.status),
        s.agent_provider ?? "\u2014",
        formatTimestamp(s.started_at),
        formatTokens(s.total_tokens),
        formatCost(s.total_cost_usd),
      );
    }
    table.print();
  },
};

const showCommand: CommandDef = {
  name: "show",
  description: "Show detailed session information",
  args: [{ name: "session-id", description: "Session ID", required: true }],
  handler: async (parsed: ParsedArgs) => {
    const id = parsed.positionals[0];
    if (!id) { printError("Missing session-id"); throw new CLIError("Missing argument", 1); }

    const d = await apiGet<SessionResponse>(`/sessions/${id}`);

    print(`${style("Session:", BOLD)} ${d.id}`);
    print(`  Workflow:    ${d.workflow_name ?? d.workflow_id ?? "\u2014"}`);
    print(`  Status:      ${formatStatus(d.status)}`);
    print(`  Provider:    ${d.agent_provider ?? "\u2014"}`);
    print(`  Model:       ${d.agent_model ?? "\u2014"}`);
    print(`  Started:     ${formatTimestamp(d.started_at)}`);
    if (d.completed_at) print(`  Completed:   ${formatTimestamp(d.completed_at)}`);
    if (d.duration_seconds != null) print(`  Duration:    ${formatDuration(d.duration_seconds * 1000)}`);
    print(`  Tokens:      ${formatTokens(d.total_tokens)} (in: ${formatTokens(d.input_tokens)}, out: ${formatTokens(d.output_tokens)})`);
    if (d.cache_creation_tokens) print(`  Cache Write: ${formatTokens(d.cache_creation_tokens)}`);
    if (d.cache_read_tokens) print(`  Cache Read:  ${formatTokens(d.cache_read_tokens)}`);
    print(`  Cost:        ${formatCost(d.total_cost_usd)}`);
    if (d.error_message) print(`  Error:       ${d.error_message}`);

    const operations = d.operations ?? [];
    if (operations.length > 0) {
      print("");
      const table = new Table({ title: "Operations" });
      table.addColumn("#", { align: "right", style: DIM });
      table.addColumn("Type", { style: CYAN });
      table.addColumn("Tool");
      table.addColumn("Success");

      for (let i = 0; i < operations.length; i++) {
        const op = operations[i]!;
        table.addRow(
          String(i + 1),
          op.operation_type,
          op.tool_name ?? "\u2014",
          op.success ? "yes" : "no",
        );
      }
      table.print();
    }
  },
};

export const sessionsGroup = new CommandGroup("sessions", "List and inspect agent sessions");
sessionsGroup.command(listCommand).command(showCommand);
