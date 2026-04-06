/**
 * Cost tracking commands — summary, sessions, session, executions, execution.
 * Port of apps/syn-cli/src/syn_cli/commands/costs.py
 */

import { CommandGroup, type CommandDef, type ParsedArgs } from "../framework/command.js";
import { CLIError } from "../framework/errors.js";
import { api, unwrap } from "../client/typed.js";
import { print, printError, printDim } from "../output/console.js";
import { style, BOLD, CYAN, DIM } from "../output/ansi.js";
import { formatCost, formatDuration, formatTimestamp, formatTokens, formatBreakdown } from "../output/format.js";
import { Table } from "../output/table.js";


function safeCost(v: string): string {
  if (v.startsWith("$")) return v;
  try { return formatCost(v); } catch { return v; }
}

const summaryCommand: CommandDef = {
  name: "summary",
  description: "Show aggregated cost summary",
  handler: async () => {
    const d = unwrap(await api.GET("/costs/summary"), "Get cost summary");

    print(style("Cost Summary", CYAN));
    print(`  ${style("Total Cost:", BOLD)} ${formatCost(d.total_cost_usd)}`);
    print(`  ${style("Sessions:", BOLD)} ${d.total_sessions}`);
    print(`  ${style("Executions:", BOLD)} ${d.total_executions}`);
    print(`  ${style("Tokens:", BOLD)} ${formatTokens(d.total_tokens)}`);
    print(`  ${style("Tool Calls:", BOLD)} ${d.total_tool_calls}`);

    const topModels = (d.top_models ?? []) as Record<string, string>[];
    if (topModels.length > 0) {
      const table = new Table({ title: "Top Models" });
      table.addColumn("Model", { style: CYAN });
      table.addColumn("Cost", { align: "right" });
      for (const e of topModels) table.addRow(e["model"] ?? "unknown", e["cost"] ?? "$0");
      table.print();
    }

    const topSessions = (d.top_sessions ?? []) as Record<string, string>[];
    if (topSessions.length > 0) {
      const table = new Table({ title: "Top Sessions" });
      table.addColumn("Session", { style: DIM });
      table.addColumn("Cost", { align: "right" });
      for (const e of topSessions) {
        const sid = e["session_id"] ?? "unknown";
        table.addRow(sid.length > 12 ? sid.slice(0, 12) + "..." : sid, e["cost"] ?? "$0");
      }
      table.print();
    }
  },
};

const sessionsCommand: CommandDef = {
  name: "sessions",
  description: "List cost data for sessions",
  options: {
    execution: { type: "string", short: "e", description: "Filter by execution ID" },
    limit: { type: "string", short: "n", description: "Max results", default: "50" },
  },
  handler: async (parsed: ParsedArgs) => {
    const limit = Number((parsed.values["limit"] as string | undefined) ?? "50");
    const items = unwrap(await api.GET("/costs/sessions", {
      params: {
        query: {
          execution_id: (parsed.values["execution"] as string | undefined) ?? null,
          limit,
        },
      },
    }), "List session costs");

    if (items.length === 0) { printDim("No session cost data found."); return; }

    const table = new Table({ title: "Session Costs" });
    table.addColumn("Session ID", { style: DIM });
    table.addColumn("Cost", { align: "right" });
    table.addColumn("Tokens", { align: "right" });
    table.addColumn("Duration", { align: "right" });
    table.addColumn("Tools", { align: "right" });

    for (const s of items) {
      const sid = s.session_id;
      table.addRow(
        sid.length > 12 ? sid.slice(0, 12) + "..." : sid,
        formatCost(s.total_cost_usd),
        formatTokens(s.total_tokens),
        formatDuration(s.duration_ms),
        String(s.tool_calls),
      );
    }
    table.print();
  },
};

const sessionDetailCommand: CommandDef = {
  name: "session",
  description: "Show detailed cost breakdown for a session",
  args: [{ name: "session-id", description: "Session ID", required: true }],
  handler: async (parsed: ParsedArgs) => {
    const id = parsed.positionals[0];
    if (!id) { printError("Missing session-id"); throw new CLIError("Missing argument", 1); }

    const s = unwrap(await api.GET("/costs/sessions/{session_id}", { params: { path: { session_id: id } } }), "Get session cost");

    print(style("Session Cost Detail", CYAN));
    print(`  ${style("Session:", BOLD)} ${s.session_id}`);
    print(`  ${style("Cost:", BOLD)} ${formatCost(s.total_cost_usd)}`);
    print(`  ${style("Tokens:", BOLD)} ${formatTokens(s.total_tokens)} (in: ${formatTokens(s.input_tokens)}, out: ${formatTokens(s.output_tokens)})`);
    print(`  ${style("Tool Calls:", BOLD)} ${s.tool_calls}  ${style("Turns:", BOLD)} ${s.turns}`);
    print(`  ${style("Duration:", BOLD)} ${formatDuration(s.duration_ms)}`);
    print(`  ${style("Started:", BOLD)} ${formatTimestamp(s.started_at)}`);

    if (s.cost_by_model && Object.keys(s.cost_by_model).length > 0) print(formatBreakdown(s.cost_by_model, "Cost by Model", safeCost));
    if (s.cost_by_tool && Object.keys(s.cost_by_tool).length > 0) print(formatBreakdown(s.cost_by_tool, "Cost by Tool", safeCost));
  },
};

const executionsCommand: CommandDef = {
  name: "executions",
  description: "List cost data for workflow executions",
  options: { limit: { type: "string", short: "n", description: "Max results", default: "50" } },
  handler: async (parsed: ParsedArgs) => {
    const limit = Number((parsed.values["limit"] as string | undefined) ?? "50");
    const items = unwrap(await api.GET("/costs/executions", { params: { query: { limit } } }), "List execution costs");

    if (items.length === 0) { printDim("No execution cost data found."); return; }

    const table = new Table({ title: "Execution Costs" });
    table.addColumn("Execution ID", { style: DIM });
    table.addColumn("Cost", { align: "right" });
    table.addColumn("Sessions", { align: "right" });
    table.addColumn("Tokens", { align: "right" });

    for (const e of items) {
      const eid = e.execution_id;
      table.addRow(
        eid.length > 12 ? eid.slice(0, 12) + "..." : eid,
        formatCost(e.total_cost_usd),
        String(e.session_count),
        formatTokens(e.total_tokens),
      );
    }
    table.print();
  },
};

const executionDetailCommand: CommandDef = {
  name: "execution",
  description: "Show detailed cost breakdown for an execution",
  args: [{ name: "execution-id", description: "Execution ID", required: true }],
  handler: async (parsed: ParsedArgs) => {
    const id = parsed.positionals[0];
    if (!id) { printError("Missing execution-id"); throw new CLIError("Missing argument", 1); }

    const e = unwrap(await api.GET("/costs/executions/{execution_id}", { params: { path: { execution_id: id } } }), "Get execution cost");

    print(style("Execution Cost Detail", CYAN));
    print(`  ${style("Execution:", BOLD)} ${e.execution_id}`);
    print(`  ${style("Cost:", BOLD)} ${formatCost(e.total_cost_usd)}`);
    print(`  ${style("Sessions:", BOLD)} ${e.session_count}`);
    print(`  ${style("Tokens:", BOLD)} ${formatTokens(e.total_tokens)} (in: ${formatTokens(e.input_tokens)}, out: ${formatTokens(e.output_tokens)})`);
    print(`  ${style("Duration:", BOLD)} ${formatDuration(e.duration_ms)}`);
    print(`  ${style("Started:", BOLD)} ${formatTimestamp(e.started_at)}`);

    if (e.cost_by_phase && Object.keys(e.cost_by_phase).length > 0) print(formatBreakdown(e.cost_by_phase, "Cost by Phase", safeCost));
    if (e.cost_by_model && Object.keys(e.cost_by_model).length > 0) print(formatBreakdown(e.cost_by_model, "Cost by Model", safeCost));
    if (e.cost_by_tool && Object.keys(e.cost_by_tool).length > 0) print(formatBreakdown(e.cost_by_tool, "Cost by Tool", safeCost));
  },
};

export const costsGroup = new CommandGroup("costs", "View cost tracking data for sessions and executions");
costsGroup.command(summaryCommand).command(sessionsCommand).command(sessionDetailCommand).command(executionsCommand).command(executionDetailCommand);
