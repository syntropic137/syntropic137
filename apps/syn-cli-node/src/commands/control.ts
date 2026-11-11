/**
 * Execution control commands - cancel, status, inject, stop.
 *
 * `inject` is refused by the API (501, #1530): nothing delivers a message into
 * a running agent. The command still asks, so the server's refusal is what the
 * operator reads, and the CLI exits non-zero with it.
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
 * A cancel of a started execution is queued, and the executor acts on it
 * later: until then `state` is the state before the cancel (#1062).
 */
const CANCEL_NOTES =
  "Cancelling a started execution is asynchronous: the signal is queued and the " +
  "executor acts on it shortly after. Until then the response's state, and any " +
  "re-read, still shows the state before the cancel (usually running), and the " +
  "command says the cancel is queued. Run `syn execution show <execution-id>` " +
  "until it reads cancelled. Cancelling a start that is still queued withdraws it " +
  "at once: it reads cancelled straight away and never runs.";

function printIfQueued(data: ControlResponse, id: string): void {
  if (data.applied !== false) return;
  printDim(`  Queued, not yet applied: run \`syn execution show ${id}\` until it reads cancelled.`);
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

const cancelCommand: CommandDef = {
  name: "cancel",
  description: "Cancel a running execution",
  notes: CANCEL_NOTES,
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
    print(`  State: ${data.state}`);
    // #1650: a queued start is withdrawn, not signalled; the message says which.
    if (data.message) print(`  Message: ${data.message}`);
    printIfQueued(data, id);
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
  description:
    "Not supported: the API refuses it. Cancel the execution and start again with a corrected task",
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
    // Only a server from before #1530 says yes, and it delivers nothing either:
    // its "queued" is still a refusal, so exit non-zero as the 501 path does.
    throw new CLIError(
      `Inject message: injecting a message into a running agent is not supported (#1530); ` +
        `nothing was delivered to execution ${id}. Cancel it and start again with a corrected task.`,
      1,
    );
  },
};

const stopCommand: CommandDef = {
  name: "stop",
  description: "Forcefully stop a running execution via SIGINT",
  notes: CANCEL_NOTES,
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
    print(`  State: ${data.state}`);
    if (data.message) print(`  Message: ${data.message}`);
    printIfQueued(data, id);
  },
};

export const controlGroup = new CommandGroup("control", "Control running executions");
controlGroup
  .command(cancelCommand)
  .command(statusCommand)
  .command(injectCommand)
  .command(stopCommand);
