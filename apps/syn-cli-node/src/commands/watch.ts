/**
 * Watch commands — live SSE streaming for executions and global activity.
 * Port of apps/syn-cli/src/syn_cli/commands/watch/_sse.py + _render.py
 */

import { CommandGroup, type CommandDef, type ParsedArgs } from "../framework/command.js";
import { CLIError } from "../framework/errors.js";
import { streamSSE, type SSEEvent } from "../client/sse.js";
import { print, printError, printDim } from "../output/console.js";
import { style, BOLD, CYAN, DIM, GREEN, RED, YELLOW } from "../output/ansi.js";
import { formatCost, formatTimestamp, formatTokens } from "../output/format.js";

const EVENT_STYLES: Record<string, string> = {
  WorkflowExecutionStarted: GREEN,
  WorkflowCompleted: GREEN,
  WorkflowFailed: RED,
  PhaseStarted: CYAN,
  PhaseCompleted: GREEN,
  PhaseFailed: RED,
  SessionTokensRecorded: DIM,
  ExecutionPaused: YELLOW,
  ExecutionResumed: GREEN,
  ExecutionCancelled: RED,
};

function extractEventId(data: Record<string, unknown>): string {
  return (data["workflow_execution_id"] ?? data["execution_id"] ?? data["session_id"] ?? "") as string;
}

function renderEventData(parts: string[], data: Record<string, unknown>): void {
  const id = extractEventId(data);
  if (id) parts.push(` ${style(id.slice(0, 12), DIM)}`);
  if (data["workflow_name"]) parts.push(` ${String(data["workflow_name"])}`);
  if (data["phase_name"]) parts.push(` phase:${String(data["phase_name"])}`);
  if (data["total_tokens"]) parts.push(` tokens:${formatTokens(Number(data["total_tokens"]))}`);
  if (data["cost_usd"]) parts.push(` cost:${formatCost(String(data["cost_usd"]))}`);
  if (data["error_message"]) parts.push(` ${style(String(data["error_message"]).slice(0, 80), RED)}`);
}

function renderEvent(event: SSEEvent): void {
  const ts = event.timestamp ? formatTimestamp(event.timestamp) : style("now", DIM);
  const eventType = event.event_type ?? event.type ?? "unknown";
  const eventStyle = EVENT_STYLES[eventType] ?? "";

  const parts = [style(ts, DIM), " ", eventStyle ? style(eventType, eventStyle) : eventType];

  if (event.data) {
    renderEventData(parts, event.data);
  }

  print(parts.join(""));
}

const executionCommand: CommandDef = {
  name: "execution",
  description: "Stream live events for a specific execution",
  args: [{ name: "execution-id", description: "Execution ID to watch", required: true }],
  handler: async (parsed: ParsedArgs) => {
    const id = parsed.positionals[0];
    if (!id) { printError("Missing execution-id"); throw new CLIError("Missing argument", 1); }

    print(style(`Watching execution ${id}...`, BOLD));
    printDim("Press Ctrl+C to stop.\n");

    try {
      for await (const event of streamSSE(`/sse/executions/${id}`)) {
        renderEvent(event);
      }
      print(style("\nStream ended.", DIM));
    } catch (err) {
      if (err instanceof CLIError) throw err;
      if (err instanceof Error && err.name === "AbortError") return;
      printError(`Stream error: ${err instanceof Error ? err.message : String(err)}`);
      throw new CLIError("Stream failed", 1);
    }
  },
};

const activityCommand: CommandDef = {
  name: "activity",
  description: "Stream live global activity across all executions",
  handler: async () => {
    print(style("Watching global activity...", BOLD));
    printDim("Press Ctrl+C to stop.\n");

    try {
      for await (const event of streamSSE("/watch/activity")) {
        renderEvent(event);
      }
      print(style("\nStream ended.", DIM));
    } catch (err) {
      if (err instanceof CLIError) throw err;
      if (err instanceof Error && err.name === "AbortError") return;
      printError(`Stream error: ${err instanceof Error ? err.message : String(err)}`);
      throw new CLIError("Stream failed", 1);
    }
  },
};

export const watchGroup = new CommandGroup("watch", "Stream live execution events via SSE");
watchGroup.command(executionCommand).command(activityCommand);
