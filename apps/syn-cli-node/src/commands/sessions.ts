/**
 * Session management commands - list, show.
 *
 * Reads server-produced *_display fields for human-readable values
 * (tokens, cost, duration, model). Locale-dependent timestamps are
 * formatted client-side from the API's ISO 8601 UTC strings.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { CommandGroup, type CommandDef, type ParsedArgs } from "../framework/command.js";
import { CLIError } from "../framework/errors.js";
import { api, unwrap } from "../client/typed.js";
import type { components } from "../generated/api-types.js";
import { print, printError, printDim } from "../output/console.js";
import { style, BOLD, CYAN, DIM } from "../output/ansi.js";
import { formatStatus, formatTimestamp } from "../output/format.js";
import { Table } from "../output/table.js";

type SessionSummary = components["schemas"]["SessionSummaryResponse"];
type SessionDetail = components["schemas"]["SessionResponse"];

const listCommand: CommandDef = {
  name: "list",
  description: "List agent sessions",
  options: {
    workflow: { type: "string", short: "w", description: "Filter by workflow ID" },
    status: { type: "string", short: "s", description: "Filter by status" },
    limit: { type: "string", short: "n", description: "Max results", default: "50" },
  },
  handler: async (parsed: ParsedArgs) => {
    const workflow = parsed.values["workflow"] as string | undefined;
    const status = parsed.values["status"] as string | undefined;
    const limitStr = (parsed.values["limit"] as string | undefined) ?? "50";

    const data = unwrap(await api.GET("/sessions", {
      params: {
        query: {
          workflow_id: workflow ?? null,
          status: status ?? null,
          limit: parseInt(limitStr, 10),
        },
      },
    }), "Failed to list sessions");

    const items: SessionSummary[] = data.sessions ?? [];
    if (items.length === 0) { printDim("No sessions found."); return; }

    const table = new Table({ title: "Sessions" });
    table.addColumn("Session ID", { style: CYAN });
    table.addColumn("Status");
    table.addColumn("Model");
    table.addColumn("Started");
    table.addColumn("Tokens", { align: "right" });
    table.addColumn("Cost", { align: "right" });

    for (const s of items) {
      table.addRow(
        s.id.slice(0, 8) + "\u2026",
        formatStatus(s.status),
        s.agent_model_display ?? s.agent_provider ?? "\u2014",
        formatTimestamp(s.started_at),
        s.total_tokens_display,
        s.total_cost_display,
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

    const d: SessionDetail = unwrap(await api.GET("/sessions/{session_id}", {
      params: { path: { session_id: id } },
    }), "Failed to get session");

    print(`${style("Session:", BOLD)} ${d.id}`);
    print(`  Workflow:    ${d.workflow_name ?? d.workflow_id ?? "\u2014"}`);
    print(`  Status:      ${formatStatus(d.status)}`);
    print(`  Provider:    ${d.agent_provider ?? "\u2014"}`);
    print(`  Model:       ${d.agent_model_display ?? d.agent_model ?? "\u2014"}`);
    print(`  Started:     ${formatTimestamp(d.started_at)}`);
    if (d.completed_at) print(`  Completed:   ${formatTimestamp(d.completed_at)}`);
    if (d.duration_seconds != null) print(`  Duration:    ${d.duration_display}`);
    print(`  Tokens:      ${d.total_tokens_display} (in: ${d.input_tokens_display}, out: ${d.output_tokens_display})`);
    if (d.cache_creation_tokens) print(`  Cache Write: ${d.cache_creation_tokens_display}`);
    if (d.cache_read_tokens) print(`  Cache Read:  ${d.cache_read_tokens_display}`);
    print(`  Cost:        ${d.total_cost_display}`);
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
