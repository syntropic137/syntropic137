import type { SyntropicClient } from "../client.js";
import { formatError } from "../errors.js";
import type { ExecutionListResponse, ExecutionSummary } from "../types.js";

// Re-export extracted execution detail function for backwards compatibility
export { synGetExecution } from "./execution_detail.js";
export type { GetExecutionArgs } from "./execution_detail.js";

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
