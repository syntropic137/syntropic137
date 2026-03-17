import type { SyntropicClient } from "../client.js";
import { formatError } from "../errors.js";
import type {
  ExecuteWorkflowResponse,
  WorkflowListResponse,
  WorkflowSummary,
} from "../types.js";

// ---------------------------------------------------------------------------
// syn_list_workflows
// ---------------------------------------------------------------------------

export interface ListWorkflowsArgs {
  workflow_type?: string;
  page?: number;
  page_size?: number;
}

export async function synListWorkflows(
  client: SyntropicClient,
  args: ListWorkflowsArgs,
): Promise<{ content: string; isError?: true }> {
  const params: Record<string, string> = {};
  if (args.workflow_type) params["workflow_type"] = args.workflow_type;
  if (args.page) params["page"] = String(args.page);
  if (args.page_size) params["page_size"] = String(args.page_size);

  const result = await client.get<WorkflowListResponse>("/workflows", params);
  if (!result.ok) return formatError(result.error);

  const { workflows, total, page, page_size } = result.data;
  if (workflows.length === 0) {
    return { content: "No workflows found." };
  }

  const lines = workflows.map((w: WorkflowSummary) =>
    `- **${w.name}** (${w.id})\n  Type: ${w.workflow_type} · ${w.phase_count} phase(s) · ${w.runs_count} run(s)`,
  );

  return {
    content: [
      `## Workflows (${total} total, page ${page}/${Math.ceil(total / page_size)})`,
      "",
      ...lines,
    ].join("\n"),
  };
}

// ---------------------------------------------------------------------------
// syn_execute_workflow
// ---------------------------------------------------------------------------

export interface ExecuteWorkflowArgs {
  workflow_id: string;
  inputs?: Record<string, string>;
  provider?: string;
  max_budget_usd?: number;
}

export async function synExecuteWorkflow(
  client: SyntropicClient,
  args: ExecuteWorkflowArgs,
): Promise<{ content: string; isError?: true }> {
  const body: Record<string, unknown> = {};
  if (args.inputs) body["inputs"] = args.inputs;
  if (args.provider) body["provider"] = args.provider;
  if (args.max_budget_usd !== undefined) body["max_budget_usd"] = args.max_budget_usd;

  const result = await client.post<ExecuteWorkflowResponse>(
    `/workflows/${encodeURIComponent(args.workflow_id)}/execute`,
    body,
  );
  if (!result.ok) return formatError(result.error);

  const { execution_id, workflow_id, status, message } = result.data;
  return {
    content: [
      `## Workflow Execution Started`,
      "",
      `- **Execution ID:** ${execution_id}`,
      `- **Workflow:** ${workflow_id}`,
      `- **Status:** ${status}`,
      `- ${message}`,
      "",
      `Use \`syn_get_execution\` with ID \`${execution_id}\` to monitor progress.`,
    ].join("\n"),
  };
}

/** Tool definitions for workflow tools. */
export const workflowToolDefs = [
  {
    name: "syn_list_workflows",
    description:
      "List available workflow templates on Syntropic137. Returns workflow names, types, phase counts, and run counts.",
    inputSchema: {
      type: "object" as const,
      properties: {
        workflow_type: {
          type: "string",
          description: "Filter by workflow type (e.g. 'issue', 'review')",
        },
        page: { type: "number", description: "Page number (default 1)" },
        page_size: {
          type: "number",
          description: "Results per page (default 20, max 100)",
        },
      },
    },
  },
  {
    name: "syn_execute_workflow",
    description:
      "Start a workflow execution on Syntropic137. Provide the workflow ID and input variables. Returns an execution ID for monitoring.",
    inputSchema: {
      type: "object" as const,
      properties: {
        workflow_id: { type: "string", description: "Workflow template ID" },
        inputs: {
          type: "object",
          description:
            "Input variables for the workflow (e.g. { issue_url: 'https://...' })",
          additionalProperties: { type: "string" },
        },
        provider: {
          type: "string",
          description: "Agent provider (default 'claude')",
        },
        max_budget_usd: {
          type: "number",
          description: "Maximum budget in USD (optional)",
        },
      },
      required: ["workflow_id"],
    },
  },
] as const;
