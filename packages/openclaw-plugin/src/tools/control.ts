import type { SyntropicClient } from "../client.js";
import { formatError } from "../errors.js";
import { formatStarted } from "./format.js";
import type { ControlResponse, ResumeResponse } from "../types.js";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------



/** The failure shape shared by every control action. */
function formatControlFailure(action: string, data: ControlResponse): { content: string; isError: true } {
  return {
    content: `Failed to ${action} execution ${data.execution_id}: ${data.error ?? "unknown error"}`,
    isError: true,
  };
}

function formatControl(action: string, data: ControlResponse): { content: string; isError?: true } {
  const past = action === "cancel" ? "cancelled" : `${action}ed`;
  if (!data.success) return formatControlFailure(action, data);
  return {
    content: `Execution ${data.execution_id} ${past} successfully. State: **${data.state}**${data.message ? ` — ${data.message}` : ""}`,
  };
}

// ---------------------------------------------------------------------------
// syn_resume_execution
// ---------------------------------------------------------------------------

export interface ResumeExecutionArgs {
  execution_id: string;
  override_cancellation?: boolean;
  acknowledge_external_effects?: boolean;
}

export async function synResumeExecution(
  client: SyntropicClient,
  args: ResumeExecutionArgs,
): Promise<{ content: string; isError?: true }> {
  const result = await client.post<ResumeResponse>(
    `/executions/${encodeURIComponent(args.execution_id)}/resume`,
    {
      override_cancellation: args.override_cancellation ?? false,
      acknowledge_external_effects: args.acknowledge_external_effects ?? false,
    },
  );
  if (!result.ok) return formatError(result.error);

  // A resume CREATES a run, so the result has to say where: the new execution
  // id alone names a different run on a different deployment (issue #1264).
  const data = result.data;
  const inherited =
    data.inherited_phase_ids.length > 0
      ? data.inherited_phase_ids.join(", ")
      : "none - the resume starts at the first phase";
  return formatStarted(client, "Execution Resumed", [
    ["Resumed from", data.parent_execution_id],
    ["New execution", data.execution_id],
    ["Resumes at", data.resume_phase_id],
    ["Inherited phases", inherited],
  ]);
}

// ---------------------------------------------------------------------------
// syn_cancel_execution
// ---------------------------------------------------------------------------

export interface CancelExecutionArgs {
  execution_id: string;
  reason?: string;
}

export async function synCancelExecution(
  client: SyntropicClient,
  args: CancelExecutionArgs,
): Promise<{ content: string; isError?: true }> {
  const body: Record<string, unknown> = {};
  if (args.reason) body["reason"] = args.reason;

  const result = await client.post<ControlResponse>(
    `/executions/${encodeURIComponent(args.execution_id)}/cancel`,
    body,
  );
  if (!result.ok) return formatError(result.error);
  return formatControl("cancel", result.data);
}

// ---------------------------------------------------------------------------
// syn_inject_context
// ---------------------------------------------------------------------------

export interface InjectContextArgs {
  execution_id: string;
  message: string;
  role?: "user" | "system";
}

export async function synInjectContext(
  client: SyntropicClient,
  args: InjectContextArgs,
): Promise<{ content: string; isError?: true }> {
  const body: Record<string, unknown> = {
    message: args.message,
  };
  if (args.role) body["role"] = args.role;

  const result = await client.post<ControlResponse>(
    `/executions/${encodeURIComponent(args.execution_id)}/inject`,
    body,
  );
  if (!result.ok) return formatError(result.error);

  if (!result.data.success) {
    return {
      content: `Failed to inject context: ${result.data.error ?? "unknown error"}`,
      isError: true,
    };
  }
  return {
    content: `Context injected into execution ${result.data.execution_id}. State: **${result.data.state}**`,
  };
}

/** Tool definitions for control tools. */
export const controlToolDefs = [
  {
    name: "syn_resume_execution",
    description:
      "Resume a FAILED or INTERRUPTED Syntropic137 execution. Creates a NEW execution that " +
      "inherits the completed phases and restarts at the first phase that did not finish.",
    inputSchema: {
      type: "object" as const,
      properties: {
        execution_id: { type: "string", description: "The execution to resume from" },
        override_cancellation: {
          type: "boolean",
          description: "Resume a CANCELLED execution. A cancel is an instruction to stop, so this is a fresh decision.",
        },
        acknowledge_external_effects: {
          type: "boolean",
          description: "Accept that re-running the resumed phase may repeat a push or publish.",
        },
      },
      required: ["execution_id"],
    },
  },
  {
    name: "syn_cancel_execution",
    description: "Cancel a running workflow execution on Syntropic137.",
    inputSchema: {
      type: "object" as const,
      properties: {
        execution_id: { type: "string", description: "Execution ID to cancel" },
        reason: { type: "string", description: "Reason for cancelling (optional)" },
      },
      required: ["execution_id"],
    },
  },
  {
    name: "syn_inject_context",
    description:
      "Send a message to a running agent execution. Useful for mid-run corrections or additional instructions.",
    inputSchema: {
      type: "object" as const,
      properties: {
        execution_id: { type: "string", description: "Execution ID" },
        message: { type: "string", description: "Message to inject" },
        role: {
          type: "string",
          enum: ["user", "system"],
          description: "Message role (default 'user')",
        },
      },
      required: ["execution_id", "message"],
    },
  },
] as const;
