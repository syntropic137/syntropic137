import type { SyntropicClient } from "../client.js";
import { formatError } from "../errors.js";
import type {
  ExecutionCost,
  MetricsResponse,
  OperationInfo,
  SessionDetail,
} from "../types.js";

// ---------------------------------------------------------------------------
// syn_get_session
// ---------------------------------------------------------------------------

export interface GetSessionArgs {
  session_id: string;
}

export async function synGetSession(
  client: SyntropicClient,
  args: GetSessionArgs,
): Promise<{ content: string; isError?: true }> {
  const result = await client.get<SessionDetail>(
    `/sessions/${encodeURIComponent(args.session_id)}`,
  );
  if (!result.ok) return formatError(result.error);

  const s = result.data;
  const sections = [
    `## Session: ${s.id}`,
    "",
    `| Field | Value |`,
    `|-------|-------|`,
    `| Status | ${s.status} |`,
    `| Agent | ${s.agent_provider ?? "—"}${s.agent_model ? ` (${s.agent_model})` : ""} |`,
    `| Tokens | ${s.total_tokens.toLocaleString()} (in: ${s.input_tokens.toLocaleString()}, out: ${s.output_tokens.toLocaleString()}) |`,
    `| Cost | $${s.total_cost_usd} |`,
  ];

  if (s.workflow_name) sections.push(`| Workflow | ${s.workflow_name} |`);
  if (s.execution_id) sections.push(`| Execution | ${s.execution_id} |`);
  if (s.duration_seconds != null) sections.push(`| Duration | ${s.duration_seconds.toFixed(1)}s |`);
  if (s.error_message) sections.push(`| Error | ${s.error_message} |`);

  if (s.operations.length > 0) {
    sections.push("", "### Operations");
    const toolOps = s.operations.filter((o: OperationInfo) => o.tool_name);
    const gitOps = s.operations.filter((o: OperationInfo) => o.git_sha);

    if (toolOps.length > 0) {
      sections.push(
        "",
        "**Tool calls:**",
        ...toolOps.slice(0, 20).map((o: OperationInfo) =>
          `- ${o.tool_name} — ${o.success ? "✓" : "✗"}${o.duration_seconds != null ? ` (${o.duration_seconds.toFixed(1)}s)` : ""}`,
        ),
      );
      if (toolOps.length > 20) sections.push(`  ... and ${toolOps.length - 20} more`);
    }

    if (gitOps.length > 0) {
      sections.push(
        "",
        "**Git operations:**",
        ...gitOps.slice(0, 10).map((o: OperationInfo) =>
          `- ${o.git_sha?.slice(0, 7)} ${o.git_message ?? ""}`,
        ),
      );
    }
  }

  return { content: sections.join("\n") };
}

// ---------------------------------------------------------------------------
// syn_get_execution_cost
// ---------------------------------------------------------------------------

export interface GetExecutionCostArgs {
  execution_id: string;
}

export async function synGetExecutionCost(
  client: SyntropicClient,
  args: GetExecutionCostArgs,
): Promise<{ content: string; isError?: true }> {
  const result = await client.get<ExecutionCost>(
    `/costs/executions/${encodeURIComponent(args.execution_id)}`,
    { include_breakdown: "true", include_session_ids: "true" },
  );
  if (!result.ok) return formatError(result.error);

  const c = result.data;
  const sections = [
    `## Cost: Execution ${c.execution_id}`,
    "",
    `| Metric | Value |`,
    `|--------|-------|`,
    `| Total Cost | $${c.total_cost_usd} |`,
    `| Token Cost | $${c.token_cost_usd} |`,
    `| Tokens | ${c.total_tokens.toLocaleString()} (in: ${c.input_tokens.toLocaleString()}, out: ${c.output_tokens.toLocaleString()}) |`,
    `| Cache | ${c.cache_creation_tokens.toLocaleString()} created, ${c.cache_read_tokens.toLocaleString()} read |`,
    `| Tool Calls | ${c.tool_calls} |`,
    `| Turns | ${c.turns} |`,
    `| Sessions | ${c.session_count} |`,
    `| Complete | ${c.is_complete ? "Yes" : "No"} |`,
  ];

  const phaseEntries = Object.entries(c.cost_by_phase);
  if (phaseEntries.length > 0) {
    sections.push("", "### Cost by Phase");
    for (const [phase, cost] of phaseEntries) {
      sections.push(`- ${phase}: $${cost}`);
    }
  }

  const modelEntries = Object.entries(c.cost_by_model);
  if (modelEntries.length > 0) {
    sections.push("", "### Cost by Model");
    for (const [model, cost] of modelEntries) {
      sections.push(`- ${model}: $${cost}`);
    }
  }

  const toolEntries = Object.entries(c.cost_by_tool);
  if (toolEntries.length > 0) {
    sections.push("", "### Cost by Tool");
    for (const [tool, cost] of toolEntries) {
      sections.push(`- ${tool}: $${cost}`);
    }
  }

  return { content: sections.join("\n") };
}

// ---------------------------------------------------------------------------
// syn_get_metrics
// ---------------------------------------------------------------------------

export interface GetMetricsArgs {
  workflow_id?: string;
}

export async function synGetMetrics(
  client: SyntropicClient,
  args: GetMetricsArgs,
): Promise<{ content: string; isError?: true }> {
  const params: Record<string, string> = {};
  if (args.workflow_id) params["workflow_id"] = args.workflow_id;

  const result = await client.get<MetricsResponse>("/metrics", params);
  if (!result.ok) return formatError(result.error);

  const m = result.data;
  const sections = [
    `## Platform Metrics`,
    "",
    `| Metric | Value |`,
    `|--------|-------|`,
    `| Workflows | ${m.total_workflows} (${m.completed_workflows} completed, ${m.failed_workflows} failed) |`,
    `| Sessions | ${m.total_sessions} |`,
    `| Tokens | ${m.total_tokens.toLocaleString()} (in: ${m.total_input_tokens.toLocaleString()}, out: ${m.total_output_tokens.toLocaleString()}) |`,
    `| Total Cost | $${m.total_cost_usd} |`,
    `| Artifacts | ${m.total_artifacts} (${(m.total_artifact_bytes / 1024).toFixed(1)} KB) |`,
  ];

  if (m.phases.length > 0) {
    sections.push("", "### Phase Breakdown");
    for (const p of m.phases) {
      sections.push(
        `- **${p.phase_name}** (${p.status}) — ${p.total_tokens.toLocaleString()} tokens, $${p.cost_usd}, ${p.duration_seconds.toFixed(1)}s`,
      );
    }
  }

  return { content: sections.join("\n") };
}

/** Tool definitions for observability tools. */
export const observabilityToolDefs = [
  {
    name: "syn_get_session",
    description:
      "Get detailed information about an agent session, including tool calls, git operations, token usage, and costs.",
    inputSchema: {
      type: "object" as const,
      properties: {
        session_id: { type: "string", description: "Session ID" },
      },
      required: ["session_id"],
    },
  },
  {
    name: "syn_get_execution_cost",
    description:
      "Get detailed cost breakdown for a workflow execution, including cost by phase, model, and tool.",
    inputSchema: {
      type: "object" as const,
      properties: {
        execution_id: { type: "string", description: "Execution ID" },
      },
      required: ["execution_id"],
    },
  },
  {
    name: "syn_get_metrics",
    description:
      "Get aggregated platform metrics — workflow counts, token usage, costs, and artifact stats. Optionally filter by workflow.",
    inputSchema: {
      type: "object" as const,
      properties: {
        workflow_id: {
          type: "string",
          description: "Filter metrics to a specific workflow (optional)",
        },
      },
    },
  },
] as const;
