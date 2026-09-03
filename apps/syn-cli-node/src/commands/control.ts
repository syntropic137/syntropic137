/**
 * Execution control commands — pause, resume, cancel, status, inject, stop.
 * Port of apps/syn-cli/src/syn_cli/commands/control.py
 */

import { CommandGroup, type CommandDef, type ParsedArgs } from "../framework/command.js";
import { CLIError } from "../framework/errors.js";
import { api, unwrap } from "../client/typed.js";
import type { components } from "../generated/api-types.js";
import { print, printError, printDim } from "../output/console.js";
import { style, GREEN, YELLOW } from "../output/ansi.js";
import { formatStatus } from "../output/format.js";

type ControlResponse = components["schemas"]["ControlResponse"];
type StateResponse = components["schemas"]["StateResponse"];

/**
 * Render the body of a control response.
 *
 * pause, resume, cancel and stop all queue a signal and return immediately, so
 * `state` is the execution's state from *before* the signal was queued. Printing
 * it as a bare `State:` under "signal sent" reads as "the command did nothing" —
 * which is how a live cancel gets reported as a stuck execution. Label it for
 * what it is, and always surface the server's own message, which says what was
 * actually queued.
 */
function printSignalQueued(data: ControlResponse): void {
  print(`  State before signal: ${data.state}`);
  if (data.message) print(`  Message: ${data.message}`);
  printDim("  Asynchronous: run `syn control status <execution-id>` for the new state.");
}

function reqId(parsed: ParsedArgs): string {
  const id = parsed.positionals[0];
  if (!id) {
    printError("execution-id is required");
    printDim("Hint: run `syn execution list` to find an execution ID.");
    throw new CLIError("Missing argument", 1);
  }
  return id;
}

const pauseCommand: CommandDef = {
  name: "pause",
  description: "Pause a running execution at the next yield point",
  args: [{ name: "execution-id", description: "Execution ID to pause", required: true }],
  options: { reason: { type: "string", short: "r", description: "Reason for pausing" } },
  handler: async (parsed: ParsedArgs) => {
    const id = reqId(parsed);
    const reason = parsed.values["reason"] as string | undefined;
    const data = unwrap<ControlResponse>(
      await api.POST("/executions/{execution_id}/pause", {
        params: { path: { execution_id: id } },
        ...(reason ? { body: { reason } } : {}),
      }),
      "Pause execution",
    );
    print(style(`Pause signal sent for execution ${id}`, GREEN));
    printSignalQueued(data);
  },
};

const resumeCommand: CommandDef = {
  name: "resume",
  description: "Resume a paused execution",
  args: [{ name: "execution-id", description: "Execution ID to resume", required: true }],
  handler: async (parsed: ParsedArgs) => {
    const id = reqId(parsed);
    const data = unwrap<ControlResponse>(
      await api.POST("/executions/{execution_id}/resume", {
        params: { path: { execution_id: id } },
      }),
      "Resume execution",
    );
    print(style(`Resume signal sent for execution ${id}`, GREEN));
    printSignalQueued(data);
  },
};

const cancelCommand: CommandDef = {
  name: "cancel",
  description: "Cancel a running or paused execution",
  args: [{ name: "execution-id", description: "Execution ID to cancel", required: true }],
  options: {
    reason: { type: "string", short: "r", description: "Reason for cancelling" },
    force: { type: "boolean", short: "f", description: "Skip confirmation prompt", default: false },
  },
  handler: async (parsed: ParsedArgs) => {
    const id = reqId(parsed);
    if (parsed.values["force"] !== true) {
      printError(`Use --force to confirm cancelling execution ${id}`);
      throw new CLIError("Confirmation required", 1);
    }
    const reason = parsed.values["reason"] as string | undefined;
    const data = unwrap<ControlResponse>(
      await api.POST("/executions/{execution_id}/cancel", {
        params: { path: { execution_id: id } },
        ...(reason ? { body: { reason } } : {}),
      }),
      "Cancel execution",
    );
    print(style(`Cancel signal sent for execution ${id}`, GREEN));
    printSignalQueued(data);
  },
};

const statusCommand: CommandDef = {
  name: "status",
  description: "Get current execution control state",
  args: [{ name: "execution-id", description: "Execution ID to check", required: true }],
  handler: async (parsed: ParsedArgs) => {
    const id = reqId(parsed);
    const data = unwrap<StateResponse>(
      await api.GET("/executions/{execution_id}/state", {
        params: { path: { execution_id: id } },
      }),
      "Get execution state",
    );
    print(`Execution: ${id}`);
    print(`State: ${formatStatus(data.state)}`);
  },
};

const injectCommand: CommandDef = {
  name: "inject",
  description: "Inject a message into a running execution",
  args: [{ name: "execution-id", description: "Execution ID", required: true }],
  options: {
    message: { type: "string", short: "m", description: "Message to inject" },
  },
  handler: async (parsed: ParsedArgs) => {
    const id = reqId(parsed);
    const message = parsed.values["message"] as string | undefined;
    if (!message) { printError("Missing --message"); throw new CLIError("Missing option", 1); }
    unwrap(
      await api.POST("/executions/{execution_id}/inject", {
        params: { path: { execution_id: id } },
        body: { message, role: "user" },
      }),
      "Inject message",
    );
    print(style(`Message injected into execution ${id}`, GREEN));
  },
};

const stopCommand: CommandDef = {
  name: "stop",
  description: "Forcefully stop a running execution via SIGINT",
  args: [{ name: "execution-id", description: "Execution ID to stop", required: true }],
  options: {
    reason: { type: "string", short: "r", description: "Reason for stopping" },
    force: { type: "boolean", short: "f", description: "Skip confirmation prompt", default: false },
  },
  handler: async (parsed: ParsedArgs) => {
    const id = reqId(parsed);
    if (parsed.values["force"] !== true) {
      printError(`Use --force to confirm stopping execution ${id}`);
      throw new CLIError("Confirmation required", 1);
    }
    const reason = (parsed.values["reason"] as string | undefined) ?? "Stopped by user via syn stop";
    const data = unwrap<ControlResponse>(
      await api.POST("/executions/{execution_id}/cancel", {
        params: { path: { execution_id: id } },
        body: { reason },
      }),
      "Stop execution",
    );
    print(style(`Stop signal sent for execution ${id}`, YELLOW));
    printSignalQueued(data);
  },
};

export const controlGroup = new CommandGroup(
  "control",
  "Control running executions",
  "`pause`, `resume`, `cancel` and `stop` are asynchronous: they queue a signal " +
    "for the executor and return straight away. The state they print is the state " +
    "read *before* the signal was queued, and `syn control status` may report that " +
    "same state for a short while afterwards. That is not a refused command - " +
    "poll `syn control status` until it changes.",
);
controlGroup
  .command(pauseCommand)
  .command(resumeCommand)
  .command(cancelCommand)
  .command(statusCommand)
  .command(injectCommand)
  .command(stopCommand);
