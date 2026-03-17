import type { SyntropicClient } from "../client.js";
import { formatError } from "../errors.js";
import type { ControlResponse } from "../types.js";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatControl(action: string, data: ControlResponse): { content: string; isError?: true } {
  if (!data.success) {
    return {
      content: `Failed to ${action} execution ${data.execution_id}: ${data.error ?? "unknown error"}`,
      isError: true,
    };
  }
  return {
    content: `Execution ${data.execution_id} ${action}d successfully. State: **${data.state}**${data.message ? ` — ${data.message}` : ""}`,
  };
}

// ---------------------------------------------------------------------------
// syn_pause_execution
// ---------------------------------------------------------------------------

export interface PauseExecutionArgs {
  execution_id: string;
  reason?: string;
}

export async function synPauseExecution(
  client: SyntropicClient,
  args: PauseExecutionArgs,
): Promise<{ content: string; isError?: true }> {
  const body: Record<string, unknown> = {};
  if (args.reason) body["reason"] = args.reason;

  const result = await client.post<ControlResponse>(
    `/executions/${encodeURIComponent(args.execution_id)}/pause`,
    body,
  );
  if (!result.ok) return formatError(result.error);
  return formatControl("pause", result.data);
}

// ---------------------------------------------------------------------------
// syn_resume_execution
// ---------------------------------------------------------------------------

export interface ResumeExecutionArgs {
  execution_id: string;
}

export async function synResumeExecution(
  client: SyntropicClient,
  args: ResumeExecutionArgs,
): Promise<{ content: string; isError?: true }> {
  const result = await client.post<ControlResponse>(
    `/executions/${encodeURIComponent(args.execution_id)}/resume`,
    {},
  );
  if (!result.ok) return formatError(result.error);
  return formatControl("resume", result.data);
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
    name: "syn_pause_execution",
    description: "Pause a running workflow execution on Syntropic137.",
    inputSchema: {
      type: "object" as const,
      properties: {
        execution_id: { type: "string", description: "Execution ID to pause" },
        reason: { type: "string", description: "Reason for pausing (optional)" },
      },
      required: ["execution_id"],
    },
  },
  {
    name: "syn_resume_execution",
    description: "Resume a paused workflow execution on Syntropic137.",
    inputSchema: {
      type: "object" as const,
      properties: {
        execution_id: { type: "string", description: "Execution ID to resume" },
      },
      required: ["execution_id"],
    },
  },
  {
    name: "syn_cancel_execution",
    description: "Cancel a running or paused workflow execution on Syntropic137.",
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
