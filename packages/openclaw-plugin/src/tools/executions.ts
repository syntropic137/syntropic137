import type { SyntropicClient } from "../client.js";
import { formatError } from "../errors.js";
import type {
  ExecutionDetail,
  ExecutionListResponse,
  ExecutionSummary,
  PhaseExecutionInfo,
} from "../types.js";

// ---------------------------------------------------------------------------
// syn_list_executions
// ---------------------------------------------------------------------------

export interface ListExecutionsArgs {
  status?: string;
  page?: number;
  page_size?: number;
}

export async function synListExecutions(
  client: SyntropicClient,
  args: ListExecutionsArgs,
): Promise<{ content: string; isError?: true }> {
  const params: Record<string, string> = {};
  if (args.status) params["status"] = args.status;
  if (args.page) params["page"] = String(args.page);
  if (args.page_size) params["page_size"] = String(args.page_size);

  const result = await client.get<ExecutionListResponse>("/executions", params);
  if (!result.ok) return formatError(result.error);

  const { executions, total, page, page_size } = result.data;
  if (executions.length === 0) {
    return { content: "No executions found." };
  }

  const lines = executions.map((e: ExecutionSummary) => {
    const cost = e.total_cost_usd !== "0" ? ` · $${e.total_cost_usd}` : "";
    return `- **${e.workflow_name}** — ${e.status}\n  ID: ${e.workflow_execution_id} · ${e.completed_phases}/${e.total_phases} phases · ${e.total_tokens} tokens${cost}`;
  });

  return {
    content: [
      `## Executions (${total} total, page ${page}/${Math.ceil(total / page_size)})`,
      "",
      ...lines,
    ].join("\n"),
  };
}

// ---------------------------------------------------------------------------
// syn_get_execution
// ---------------------------------------------------------------------------

export interface GetExecutionArgs {
  execution_id: string;
}

export async function synGetExecution(
  client: SyntropicClient,
  args: GetExecutionArgs,
): Promise<{ content: string; isError?: true }> {
  const result = await client.get<ExecutionDetail>(
    `/executions/${encodeURIComponent(args.execution_id)}`,
  );
  if (!result.ok) return formatError(result.error);

  const d = result.data;
  const phaseLines = d.phases.map((p: PhaseExecutionInfo) => {
    const dur = p.duration_seconds > 0 ? ` · ${p.duration_seconds.toFixed(1)}s` : "";
    const cost = p.cost_usd !== "0" ? ` · $${p.cost_usd}` : "";
    return `  - **${p.name}** — ${p.status}${dur}${cost}`;
  });

  const sections = [
    `## Execution: ${d.workflow_name}`,
    "",
    `| Field | Value |`,
    `|-------|-------|`,
    `| ID | ${d.workflow_execution_id} |`,
    `| Workflow | ${d.workflow_id} |`,
    `| Status | ${d.status} |`,
    `| Tokens | ${d.total_tokens.toLocaleString()} (in: ${d.total_input_tokens.toLocaleString()}, out: ${d.total_output_tokens.toLocaleString()}) |`,
    `| Cost | $${d.total_cost_usd} |`,
    `| Duration | ${d.total_duration_seconds.toFixed(1)}s |`,
  ];

  if (d.started_at) sections.push(`| Started | ${d.started_at} |`);
  if (d.completed_at) sections.push(`| Completed | ${d.completed_at} |`);
  if (d.error_message) sections.push(`| Error | ${d.error_message} |`);

  if (phaseLines.length > 0) {
    sections.push("", "### Phases", ...phaseLines);
  }

  if (d.artifact_ids.length > 0) {
    sections.push("", `### Artifacts: ${d.artifact_ids.join(", ")}`);
  }

  return { content: sections.join("\n") };
}

/** Tool definitions for execution tools. */
export const executionToolDefs = [
  {
    name: "syn_list_executions",
    description:
      "List recent workflow executions on Syntropic137. Shows status, progress, token usage, and cost.",
    inputSchema: {
      type: "object" as const,
      properties: {
        status: {
          type: "string",
          description:
            "Filter by status (e.g. 'running', 'completed', 'failed')",
        },
        page: { type: "number", description: "Page number (default 1)" },
        page_size: {
          type: "number",
          description: "Results per page (default 50, max 100)",
        },
      },
    },
  },
  {
    name: "syn_get_execution",
    description:
      "Get detailed information about a specific workflow execution, including phase breakdown, token counts, costs, and artifacts.",
    inputSchema: {
      type: "object" as const,
      properties: {
        execution_id: { type: "string", description: "Execution ID" },
      },
      required: ["execution_id"],
    },
  },
] as const;
