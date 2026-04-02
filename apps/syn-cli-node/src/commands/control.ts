/**
 * Execution control commands — pause, resume, cancel, status, inject, stop.
 * Port of apps/syn-cli/src/syn_cli/commands/control.py
 */

import { CommandGroup, type CommandDef, type ParsedArgs } from "../framework/command.js";
import { CLIError } from "../framework/errors.js";
import { apiGet, apiPost } from "../client/api.js";
import { print, printError } from "../output/console.js";
import { style, GREEN, YELLOW } from "../output/ansi.js";
import { formatStatus } from "../output/format.js";
import type { ControlResponse, StateResponse } from "../generated/types.js";

function reqId(parsed: ParsedArgs): string {
  const id = parsed.positionals[0];
  if (!id) { printError("Missing execution-id"); throw new CLIError("Missing argument", 1); }
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
    const data = await apiPost<ControlResponse>(`/executions/${id}/pause`, {
      ...(reason ? { body: { reason } } : {}),
    });
    print(style(`Pause signal sent for execution ${id}`, GREEN));
    print(`  State: ${data.state}`);
    if (data.message) print(`  Message: ${data.message}`);
  },
};

const resumeCommand: CommandDef = {
  name: "resume",
  description: "Resume a paused execution",
  args: [{ name: "execution-id", description: "Execution ID to resume", required: true }],
  handler: async (parsed: ParsedArgs) => {
    const id = reqId(parsed);
    const data = await apiPost<ControlResponse>(`/executions/${id}/resume`);
    print(style(`Resume signal sent for execution ${id}`, GREEN));
    print(`  State: ${data.state}`);
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
    const data = await apiPost<ControlResponse>(`/executions/${id}/cancel`, {
      ...(reason ? { body: { reason } } : {}),
    });
    print(style(`Cancel signal sent for execution ${id}`, GREEN));
    print(`  State: ${data.state}`);
  },
};

const statusCommand: CommandDef = {
  name: "status",
  description: "Get current execution control state",
  args: [{ name: "execution-id", description: "Execution ID to check", required: true }],
  handler: async (parsed: ParsedArgs) => {
    const id = reqId(parsed);
    const data = await apiGet<StateResponse>(`/executions/${id}/state`);
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
    await apiPost(`/executions/${id}/inject`, { body: { message } });
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
    const data = await apiPost<ControlResponse>(`/executions/${id}/cancel`, {
      body: { reason },
    });
    print(style(`Stop signal sent for execution ${id}`, YELLOW));
    print(`  State: ${data.state}`);
    if (data.message) print(`  Message: ${data.message}`);
  },
};

export const controlGroup = new CommandGroup("control", "Control running executions");
controlGroup
  .command(pauseCommand)
  .command(resumeCommand)
  .command(cancelCommand)
  .command(statusCommand)
  .command(injectCommand)
  .command(stopCommand);
