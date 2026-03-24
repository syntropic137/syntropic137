import type { SyntropicClient } from "../client.js";
import { formatError } from "../errors.js";
import type { ExecutionCost, MetricsResponse } from "../types.js";
import { buildBreakdownSection, buildMarkdownTable } from "./format.js";

// Re-export extracted session functions for backwards compatibility
export { synGetSession, formatOperations } from "./observability_session.js";
export type { GetSessionArgs } from "./observability_session.js";

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
    ...buildMarkdownTable(`Cost: Execution ${c.execution_id}`, [
      ["Total Cost", `$${c.total_cost_usd}`],
      ["Token Cost", `$${c.token_cost_usd}`],
      ["Tokens", `${c.total_tokens.toLocaleString()} (in: ${c.input_tokens.toLocaleString()}, out: ${c.output_tokens.toLocaleString()})`],
      ["Cache", `${c.cache_creation_tokens.toLocaleString()} created, ${c.cache_read_tokens.toLocaleString()} read`],
      ["Tool Calls", String(c.tool_calls)],
      ["Turns", String(c.turns)],
      ["Sessions", String(c.session_count)],
      ["Complete", c.is_complete ? "Yes" : "No"],
    ]),
    ...buildBreakdownSection("Cost by Phase", Object.entries(c.cost_by_phase)),
    ...buildBreakdownSection("Cost by Model", Object.entries(c.cost_by_model)),
    ...buildBreakdownSection("Cost by Tool", Object.entries(c.cost_by_tool)),
  ];

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
    ...buildMarkdownTable("Platform Metrics", [
      ["Workflows", `${m.total_workflows} (${m.completed_workflows} completed, ${m.failed_workflows} failed)`],
      ["Sessions", String(m.total_sessions)],
      ["Tokens", `${m.total_tokens.toLocaleString()} (in: ${m.total_input_tokens.toLocaleString()}, out: ${m.total_output_tokens.toLocaleString()})`],
      ["Total Cost", `$${m.total_cost_usd}`],
      ["Artifacts", `${m.total_artifacts} (${(m.total_artifact_bytes / 1024).toFixed(1)} KB)`],
    ]),
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
