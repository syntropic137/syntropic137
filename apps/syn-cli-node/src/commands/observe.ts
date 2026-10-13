/**
 * Observability commands: tool timeline, token metrics, API request latency.
 * Port of apps/syn-cli/src/syn_cli/commands/observe.py
 */

import { CommandGroup, type CommandDef, type ParsedArgs } from "../framework/command.js";
import { CLIError } from "../framework/errors.js";
import { api, unwrap } from "../client/typed.js";
import type { components } from "../generated/api-types.js";
import { print, printError, printDim } from "../output/console.js";
import { style, BOLD, CYAN, DIM, GREEN, RED, YELLOW } from "../output/ansi.js";
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

const LATENCY_WINDOWS = ["1h", "24h", "7d", "30d"] as const;
type LatencyWindow = (typeof LATENCY_WINDOWS)[number];

function isLatencyWindow(value: string): value is LatencyWindow {
  return (LATENCY_WINDOWS as readonly string[]).includes(value);
}

const latencyCommand: CommandDef = {
  name: "latency",
  description: "Show API latency to response start (p50/p95/p99) per route",
  options: {
    window: { type: "string", short: "w", description: "1h, 24h, 7d or 30d", default: "24h" },
    route: { type: "string", short: "r", description: "One route template as the API reports it, e.g. /evals" },
  },
  handler: async (parsed: ParsedArgs) => {
    const window = (parsed.values["window"] as string | undefined) ?? "24h";
    if (!isLatencyWindow(window)) {
      throw new Error(`--window must be one of ${LATENCY_WINDOWS.join(", ")}`);
    }
    const route = parsed.values["route"] as string | undefined;
    const d = unwrap(await api.GET("/observability/latency", {
      params: { query: { window, ...(route ? { route } : {}) } },
    }), "Fetch latency");

    // Recorder health first: an empty table is exactly when the drop counters matter.
    const rec = d.recorder;
    if (!rec.running || rec.dropped > 0 || rec.write_failures > 0 || rec.discarded > 0 || rec.cleanup_failures > 0) {
      print(style(
        `  recorder ${rec.running ? "running" : "NOT running"} on this API process: `
          + `${rec.dropped} dropped, ${rec.write_failures} failed writes, ${rec.discarded} discarded, `
          + `${rec.cleanup_failures} connection cleanups failed`,
        YELLOW,
      ));
    }
    if (!d.available) { printDim("Latency store unavailable."); return; }
    if (d.routes.length === 0) { printDim(`No requests recorded in the last ${d.window}.`); return; }

    const ms = (v: number) => `${Math.round(v)}`;
    const table = new Table({ title: `Latency, arrival to response start, last ${d.window} (ms)` });
    table.addColumn("Method");
    table.addColumn("Route", { style: CYAN });
    table.addColumn("Count", { align: "right" });
    table.addColumn("p50", { align: "right" });
    table.addColumn("p95", { align: "right" });
    table.addColumn("p99", { align: "right" });
    table.addColumn("Max", { align: "right" });
    for (const r of d.routes) {
      table.addRow(r.method, r.route, String(r.count), ms(r.p50_ms), ms(r.p95_ms), ms(r.p99_ms), ms(r.max_ms));
    }
    table.print();
  },
};

export const observeGroup = new CommandGroup("observe", "Observability: session tool timelines, token metrics, API request latency");
observeGroup.command(toolTimelineCommand).command(tokenMetricsCommand).command(latencyCommand);
