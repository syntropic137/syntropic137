/**
 * Event query commands — recent, session, timeline, costs, tools.
 * Port of apps/syn-cli/src/syn_cli/commands/events.py
 */

import { CommandGroup, type CommandDef, type ParsedArgs } from "../framework/command.js";
import { CLIError } from "../framework/errors.js";
import { api, unwrap } from "../client/typed.js";
import type { components } from "../generated/api-types.js";
import { print, printError, printDim } from "../output/console.js";
import { style, BOLD, CYAN, DIM, GREEN, RED } from "../output/ansi.js";
import { formatCost, formatDuration, formatTimestamp } from "../output/format.js";
import { Table } from "../output/table.js";

type EventList = components["schemas"]["EventListResponse"];
type CostSummary = components["schemas"]["syn_api__routes__events__CostSummaryResponse"];
type TimelineEntry = components["schemas"]["TimelineEntryResponse"];
type ToolSummaryItem = components["schemas"]["ToolSummary"];

function reqSessionId(parsed: ParsedArgs): string {
  const id = parsed.positionals[0];
  if (!id) { printError("Missing session-id"); throw new CLIError("Missing argument", 1); }
  return id;
}

const recentCommand: CommandDef = {
  name: "recent",
  description: "Show recent domain events across all sessions",
  options: {
    limit: { type: "string", description: "Max events (max 200)", default: "50" },
    type: { type: "string", short: "t", description: "Filter by event type" },
  },
  handler: async (parsed: ParsedArgs) => {
    const limitStr = (parsed.values["limit"] as string | undefined) ?? "50";
    const eventType = parsed.values["type"] as string | undefined;

    const data: EventList = unwrap(await api.GET("/events/recent", {
      params: {
        query: {
          limit: parseInt(limitStr, 10),
          event_type: eventType ?? null,
        },
      },
    }), "Failed to fetch recent events");

    if (data.events.length === 0) { printDim("No recent events."); return; }

    const table = new Table({ title: "Recent Events" });
    table.addColumn("Time");
    table.addColumn("Type", { style: CYAN });
    table.addColumn("Session", { style: DIM });
    table.addColumn("Execution", { style: DIM });

    for (const ev of data.events) {
      table.addRow(
        formatTimestamp(String(ev.time ?? "")),
        ev.event_type,
        (ev.session_id ?? "").slice(0, 12),
        (ev.execution_id ?? "").slice(0, 12),
      );
    }
    table.print();
    if (data.has_more) printDim("More events available. Use --limit to fetch more.");
  },
};

const sessionEventsCommand: CommandDef = {
  name: "session",
  description: "List events for a specific session",
  args: [{ name: "session-id", description: "Session ID", required: true }],
  options: {
    type: { type: "string", short: "t", description: "Filter by event type" },
    limit: { type: "string", description: "Max events (max 1000)", default: "100" },
    offset: { type: "string", description: "Pagination offset", default: "0" },
  },
  handler: async (parsed: ParsedArgs) => {
    const sid = reqSessionId(parsed);
    const limitStr = (parsed.values["limit"] as string | undefined) ?? "100";
    const offsetStr = (parsed.values["offset"] as string | undefined) ?? "0";
    const eventType = parsed.values["type"] as string | undefined;

    const data: EventList = unwrap(await api.GET("/events/sessions/{session_id}", {
      params: {
        path: { session_id: sid },
        query: {
          limit: parseInt(limitStr, 10),
          offset: parseInt(offsetStr, 10),
          event_type: eventType ?? null,
        },
      },
    }), "Failed to fetch session events");

    if (data.events.length === 0) { printDim(`No events for session ${sid}.`); return; }

    const table = new Table({ title: `Events: ${sid.slice(0, 12)}` });
    table.addColumn("Time");
    table.addColumn("Type", { style: CYAN });
    table.addColumn("Phase", { style: DIM });

    for (const ev of data.events) {
      table.addRow(
        formatTimestamp(String(ev.time ?? "")),
        ev.event_type,
        (ev.phase_id ?? "").slice(0, 12),
      );
    }
    table.print();
    const offset = parseInt(offsetStr, 10);
    const limit = parseInt(limitStr, 10);
    if (data.has_more) printDim(`More events available. Use --offset ${offset + limit}.`);
  },
};

const timelineCommand: CommandDef = {
  name: "timeline",
  description: "Show a chronological tool-call timeline for a session",
  args: [{ name: "session-id", description: "Session ID", required: true }],
  options: { limit: { type: "string", description: "Max entries (max 500)", default: "100" } },
  handler: async (parsed: ParsedArgs) => {
    const sid = reqSessionId(parsed);
    const limitStr = (parsed.values["limit"] as string | undefined) ?? "100";

    const entries: TimelineEntry[] = unwrap(await api.GET("/events/sessions/{session_id}/timeline", {
      params: {
        path: { session_id: sid },
        query: { limit: parseInt(limitStr, 10) },
      },
    }), "Failed to fetch timeline");

    if (entries.length === 0) { printDim("No timeline entries."); return; }

    const table = new Table({ title: `Timeline: ${sid.slice(0, 12)}` });
    table.addColumn("Time");
    table.addColumn("Event", { style: CYAN });
    table.addColumn("Tool");
    table.addColumn("Duration", { align: "right" });
    table.addColumn("\u2713");

    for (const e of entries) {
      table.addRow(
        formatTimestamp(String(e.time ?? "")),
        e.event_type,
        e.tool_name ?? "\u2014",
        e.duration_ms != null ? formatDuration(e.duration_ms) : "\u2014",
        e.success === true ? style("\u2713", GREEN) : (e.success === false ? style("\u2717", RED) : "\u2014"),
      );
    }
    table.print();
  },
};

const costsCommand: CommandDef = {
  name: "costs",
  description: "Show token usage and cost breakdown for a session",
  args: [{ name: "session-id", description: "Session ID", required: true }],
  handler: async (parsed: ParsedArgs) => {
    const sid = reqSessionId(parsed);

    const d: CostSummary = unwrap(await api.GET("/events/sessions/{session_id}/costs", {
      params: { path: { session_id: sid } },
    }), "Failed to fetch session costs");

    print(`${style("Session costs:", BOLD)} ${d.session_id}`);
    print(`  Input tokens:       ${d.input_tokens.toLocaleString()}`);
    print(`  Output tokens:      ${d.output_tokens.toLocaleString()}`);
    print(`  Total tokens:       ${d.total_tokens.toLocaleString()}`);
    if (d.cache_creation_tokens) print(`  Cache creation:     ${d.cache_creation_tokens.toLocaleString()}`);
    if (d.cache_read_tokens) print(`  Cache read:         ${d.cache_read_tokens.toLocaleString()}`);
    if (d.estimated_cost_usd != null)
      print(`  Estimated cost:     ${formatCost(String(d.estimated_cost_usd))}`);
  },
};

const toolsCommand: CommandDef = {
  name: "tools",
  description: "Show tool usage summary for a session",
  args: [{ name: "session-id", description: "Session ID", required: true }],
  handler: async (parsed: ParsedArgs) => {
    const sid = reqSessionId(parsed);

    const tools: ToolSummaryItem[] = unwrap(await api.GET("/events/sessions/{session_id}/tools", {
      params: { path: { session_id: sid } },
    }), "Failed to fetch tool summary");

    if (tools.length === 0) { printDim("No tool usage recorded."); return; }

    const table = new Table({ title: `Tool Usage: ${sid.slice(0, 12)}` });
    table.addColumn("Tool", { style: CYAN });
    table.addColumn("Calls", { align: "right" });
    table.addColumn("Success", { align: "right" });
    table.addColumn("Errors", { align: "right" });
    table.addColumn("Avg Duration", { align: "right" });

    const sorted = [...tools].sort((a, b) => b.call_count - a.call_count);
    for (const t of sorted) {
      table.addRow(
        t.tool_name,
        String(t.call_count),
        String(t.success_count),
        String(t.error_count),
        t.avg_duration_ms ? formatDuration(t.avg_duration_ms) : "\u2014",
      );
    }
    table.print();
  },
};

export const eventsGroup = new CommandGroup("events", "Query domain events and session observability");
eventsGroup.command(recentCommand).command(sessionEventsCommand).command(timelineCommand).command(costsCommand).command(toolsCommand);
