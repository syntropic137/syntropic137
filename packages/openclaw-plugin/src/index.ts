import { SyntropicClient, resolveConfig } from "./client.js";
import type { SyntropicClientConfig } from "./client.js";
import { formatError } from "./errors.js";
import { synGetArtifact, synListArtifacts, artifactToolDefs } from "./tools/artifacts.js";
import { synCancelExecution, synInjectContext, synPauseExecution, synResumeExecution, controlToolDefs } from "./tools/control.js";
import { synGetExecution, synListExecutions, executionToolDefs } from "./tools/executions.js";
import { synGetExecutionCost, synGetMetrics, synGetSession, observabilityToolDefs } from "./tools/observability.js";
import { synCreateTrigger, synListTriggers, triggerToolDefs } from "./tools/triggers.js";
import { synExecuteWorkflow, synListWorkflows, workflowToolDefs } from "./tools/workflows.js";

// ---------------------------------------------------------------------------
// Tool registry
// ---------------------------------------------------------------------------

export const allToolDefs = [
  ...workflowToolDefs,
  ...executionToolDefs,
  ...controlToolDefs,
  ...observabilityToolDefs,
  ...artifactToolDefs,
  ...triggerToolDefs,
];

type ToolResult = Promise<{ content: string; isError?: true }>;

// eslint-disable-next-line @typescript-eslint/no-explicit-any -- runtime args from OpenClaw are untyped
type ToolHandler = (client: SyntropicClient, args: any) => ToolResult;

const toolHandlers: Record<string, ToolHandler> = {
  syn_list_workflows: synListWorkflows,
  syn_execute_workflow: synExecuteWorkflow,
  syn_list_executions: synListExecutions,
  syn_get_execution: synGetExecution,
  syn_pause_execution: synPauseExecution,
  syn_resume_execution: synResumeExecution,
  syn_cancel_execution: synCancelExecution,
  syn_inject_context: synInjectContext,
  syn_get_session: synGetSession,
  syn_get_execution_cost: synGetExecutionCost,
  syn_get_metrics: synGetMetrics,
  syn_list_artifacts: synListArtifacts,
  syn_get_artifact: synGetArtifact,
  syn_list_triggers: synListTriggers,
  syn_create_trigger: synCreateTrigger,
};

// ---------------------------------------------------------------------------
// Plugin entry point
// ---------------------------------------------------------------------------

export interface PluginApi {
  registerTool(def: {
    name: string;
    description: string;
    inputSchema: Record<string, unknown>;
    handler: (args: Record<string, unknown>) => Promise<{ content: string; isError?: true }>;
  }): void;
}

/**
 * OpenClaw plugin entry point.
 *
 * Called by the OpenClaw runtime with plugin config and the registration API.
 */
export function definePluginEntry(
  pluginConfig: Partial<SyntropicClientConfig> | undefined,
  api: PluginApi,
): void {
  const config = resolveConfig(pluginConfig);
  const client = new SyntropicClient(config);

  for (const def of allToolDefs) {
    const handler = toolHandlers[def.name];
    if (!handler) continue;

    api.registerTool({
      name: def.name,
      description: def.description,
      inputSchema: def.inputSchema as Record<string, unknown>,
      handler: async (args: Record<string, unknown>) => {
        try {
          return await handler(client, args);
        } catch (err) {
          return formatError(err);
        }
      },
    });
  }
}

// Re-export for consumers
export { SyntropicClient, resolveConfig } from "./client.js";
export type { SyntropicClientConfig } from "./client.js";
export { formatError, ApiError } from "./errors.js";
