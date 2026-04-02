/**
 * Conversation log commands — show, metadata.
 * Port of apps/syn-cli/src/syn_cli/commands/conversations.py
 */

import { CommandGroup, type CommandDef, type ParsedArgs } from "../framework/command.js";
import { CLIError } from "../framework/errors.js";
import { apiGet } from "../client/api.js";
import { print, printError, printDim } from "../output/console.js";
import { style, BOLD, CYAN, DIM } from "../output/ansi.js";
import { formatTimestamp } from "../output/format.js";
import { Table } from "../output/table.js";
import type { ConversationLogResponse, ConversationMetadataResponse } from "../generated/types.js";

const showCommand: CommandDef = {
  name: "show",
  description: "Show parsed conversation log lines for a session",
  args: [{ name: "session-id", description: "Session ID", required: true }],
  options: {
    offset: { type: "string", description: "Line offset for pagination", default: "0" },
    limit: { type: "string", description: "Max lines to show (max 500)", default: "100" },
  },
  handler: async (parsed: ParsedArgs) => {
    const sessionId = parsed.positionals[0];
    if (!sessionId) { printError("Missing session-id"); throw new CLIError("Missing argument", 1); }
    const offset = parseInt((parsed.values["offset"] as string) ?? "0", 10);
    const limit = parseInt((parsed.values["limit"] as string) ?? "100", 10);

    const data = await apiGet<ConversationLogResponse>(`/conversations/${sessionId}`, {
      params: { offset, limit },
    });

    if (data.lines.length === 0) { printDim("No conversation lines found."); return; }

    print(`${style("Conversation:", BOLD)} ${sessionId.slice(0, 16)}  ${style(`(lines ${offset + 1}-${offset + data.lines.length} of ${data.total_lines})`, DIM)}`);
    print("");

    const table = new Table();
    table.addColumn("#", { align: "right", style: DIM });
    table.addColumn("Type", { style: CYAN });
    table.addColumn("Tool", { style: DIM });
    table.addColumn("Preview");

    for (const line of data.lines) {
      table.addRow(
        String(line.line_number),
        line.event_type ?? "\u2014",
        line.tool_name ?? "\u2014",
        line.content_preview ?? "\u2014",
      );
    }
    table.print();

    if (data.total_lines > offset + data.lines.length) {
      printDim(`More lines available. Use --offset ${offset + limit}.`);
    }
  },
};

const metadataCommand: CommandDef = {
  name: "metadata",
  description: "Show metadata summary for a session's conversation",
  args: [{ name: "session-id", description: "Session ID", required: true }],
  handler: async (parsed: ParsedArgs) => {
    const sessionId = parsed.positionals[0];
    if (!sessionId) { printError("Missing session-id"); throw new CLIError("Missing argument", 1); }

    const m = await apiGet<ConversationMetadataResponse>(`/conversations/${sessionId}/metadata`);

    print(`${style("Metadata:", BOLD)} ${m.session_id}`);

    if (m.model != null) print(`  Model:            ${m.model}`);
    if (m.event_count != null) print(`  Events:           ${m.event_count.toLocaleString()}`);
    if (m.total_input_tokens != null) print(`  Input tokens:     ${m.total_input_tokens.toLocaleString()}`);
    if (m.total_output_tokens != null) print(`  Output tokens:    ${m.total_output_tokens.toLocaleString()}`);
    if (m.started_at != null) print(`  Started:          ${formatTimestamp(m.started_at)}`);
    if (m.completed_at != null) print(`  Completed:        ${formatTimestamp(m.completed_at)}`);
    if (m.size_bytes != null) print(`  Log size:         ${m.size_bytes.toLocaleString()} bytes`);

    if (m.tool_counts) {
      print("  Tool counts:");
      const sorted = Object.entries(m.tool_counts).sort(([, a], [, b]) => b - a);
      for (const [tool, count] of sorted) {
        print(`    ${tool}: ${count}`);
      }
    }
  },
};

export const conversationsGroup = new CommandGroup("conversations", "Inspect agent conversation logs");
conversationsGroup.command(showCommand).command(metadataCommand);
