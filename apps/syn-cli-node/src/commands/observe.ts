/**
 * Observability commands — tool timeline, token metrics.
 * Port of apps/syn-cli/src/syn_cli/commands/observe.py
 */

import { CommandGroup, type CommandDef, type ParsedArgs } from "../framework/command.js";
import { CLIError } from "../framework/errors.js";
import { api, unwrap } from "../client/typed.js";
import type { components } from "../generated/api-types.js";
import { print, printError, printDim } from "../output/console.js";
import { style, BOLD, CYAN, DIM, GREEN, RED } from "../output/ansi.js";
import { formatCost, formatDuration, formatTimestamp } from "../output/format.js";
import { Table } from "../output/table.js";

type ToolTimeline = components["schemas"]["ToolTimelineResponse"];
type ToolTimelineEntry = components["schemas"]["ToolTimelineEntry"];
type TokenMetrics = components["schemas"]["SessionTokenMetrics"];

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
    const limitStr = (parsed.values["limit"] as string | undefined) ?? "100";

    const data: ToolTimeline = unwrap(await api.GET("/observability/sessions/{session_id}/tools", {
      params: {
        path: { session_id: sid },
        query: { limit: parseInt(limitStr, 10) },
      },
    }), "Failed to fetch tool timeline");

    const entries: ToolTimelineEntry[] = data.executions ?? [];
    if (entries.length === 0) { printDim("No tool timeline entries."); return; }

    const table = new Table({ title: `Tool Timeline: ${sid.slice(0, 12)}` });
    table.addColumn("Time");
    table.addColumn("Tool", { style: CYAN });
    table.addColumn("Duration", { align: "right" });
    table.addColumn("Status");

    for (const e of entries) {
      table.addRow(
        formatTimestamp(String(e.timestamp ?? "")),
        e.tool_name ?? "",
        e.duration_ms != null ? formatDuration(e.duration_ms) : "\u2014",
        e.success === true ? style("ok", GREEN) : e.success === false ? style("error", RED) : style("\u2014", DIM),
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

    const d: TokenMetrics = unwrap(await api.GET("/observability/sessions/{session_id}/tokens", {
      params: { path: { session_id: sid } },
    }), "Failed to fetch token metrics");

    print(`${style("Token Metrics:", BOLD)} ${d.session_id}`);
    print(`  Input tokens:       ${d.input_tokens.toLocaleString()}`);
    print(`  Output tokens:      ${d.output_tokens.toLocaleString()}`);
    print(`  Total tokens:       ${d.total_tokens.toLocaleString()}`);
    if (d.cache_creation_tokens) print(`  Cache creation:     ${d.cache_creation_tokens.toLocaleString()}`);
    if (d.cache_read_tokens) print(`  Cache read:         ${d.cache_read_tokens.toLocaleString()}`);
    if (d.total_cost_usd !== "0")
      print(`  Estimated cost:     ${formatCost(d.total_cost_usd)}`);
  },
};

export const observeGroup = new CommandGroup("observe", "Session observability: tool timelines and token metrics");
observeGroup.command(toolTimelineCommand).command(tokenMetricsCommand);
