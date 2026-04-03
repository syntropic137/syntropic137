/**
 * Observability commands — tool timeline, token metrics.
 * Port of apps/syn-cli/src/syn_cli/commands/observe.py
 */

import { CommandGroup, type CommandDef, type ParsedArgs } from "../framework/command.js";
import { CLIError } from "../framework/errors.js";
import { apiGet, apiGetPaginated } from "../client/api.js";
import { print, printError, printDim } from "../output/console.js";
import { style, BOLD, CYAN, DIM, GREEN, RED } from "../output/ansi.js";
import { formatCost, formatDuration, formatTimestamp } from "../output/format.js";
import { Table } from "../output/table.js";

function reqSessionId(parsed: ParsedArgs): string {
  const id = parsed.positionals[0];
  if (!id) { printError("Missing session-id"); throw new CLIError("Missing argument", 1); }
  return id;
}

const toolTimelineCommand: CommandDef = {
  name: "tools",
  description: "Show tool execution timeline for a session",
  args: [{ name: "session-id", description: "Session ID", required: true }],
  options: {
    limit: { type: "string", description: "Max entries", default: "100" },
  },
  handler: async (parsed: ParsedArgs) => {
    const sid = reqSessionId(parsed);
    const limit = (parsed.values["limit"] as string | undefined) ?? "100";
    const entries = await apiGetPaginated<Record<string, unknown>>(`/observability/sessions/${sid}/tools`, "executions", { params: { limit } });
    if (entries.length === 0) { printDim("No tool timeline entries."); return; }

    const table = new Table({ title: `Tool Timeline: ${sid.slice(0, 12)}` });
    table.addColumn("Time");
    table.addColumn("Tool", { style: CYAN });
    table.addColumn("Duration", { align: "right" });
    table.addColumn("Status");

    for (const e of entries) {
      const dur = e["duration_ms"];
      const success = e["success"];
      table.addRow(
        formatTimestamp(String(e["time"] ?? "")),
        String(e["tool_name"] ?? ""),
        dur !== null && dur !== undefined ? formatDuration(Number(dur)) : "\u2014",
        success === true ? style("ok", GREEN) : success === false ? style("error", RED) : style("\u2014", DIM),
      );
    }
    table.print();
  },
};

const tokenMetricsCommand: CommandDef = {
  name: "tokens",
  description: "Show token breakdown for a session",
  args: [{ name: "session-id", description: "Session ID", required: true }],
  handler: async (parsed: ParsedArgs) => {
    const sid = reqSessionId(parsed);
    const d = await apiGet<Record<string, unknown>>(`/observability/sessions/${sid}/tokens`);

    print(`${style("Token Metrics:", BOLD)} ${d["session_id"] ?? sid}`);
    print(`  Input tokens:       ${Number(d["input_tokens"] ?? 0).toLocaleString()}`);
    print(`  Output tokens:      ${Number(d["output_tokens"] ?? 0).toLocaleString()}`);
    print(`  Total tokens:       ${Number(d["total_tokens"] ?? 0).toLocaleString()}`);
    if (d["cache_creation_tokens"]) print(`  Cache creation:     ${Number(d["cache_creation_tokens"]).toLocaleString()}`);
    if (d["cache_read_tokens"]) print(`  Cache read:         ${Number(d["cache_read_tokens"]).toLocaleString()}`);
    if (d["estimated_cost_usd"] !== null && d["estimated_cost_usd"] !== undefined)
      print(`  Estimated cost:     ${formatCost(String(d["estimated_cost_usd"]))}`);
  },
};

export const observeGroup = new CommandGroup("observe", "Session observability — tool timelines and token metrics");
observeGroup.command(toolTimelineCommand).command(tokenMetricsCommand);
