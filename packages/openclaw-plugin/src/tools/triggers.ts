import type { SyntropicClient } from "../client.js";
import { formatError } from "../errors.js";
import type {
  TriggerCreateResponse,
  TriggerListResponse,
  TriggerSummary,
} from "../types.js";

// ---------------------------------------------------------------------------
// syn_list_triggers
// ---------------------------------------------------------------------------

export interface ListTriggersArgs {
  repository?: string;
  status?: string;
}

export async function synListTriggers(
  client: SyntropicClient,
  args: ListTriggersArgs,
): Promise<{ content: string; isError?: true }> {
  const params: Record<string, string> = {};
  if (args.repository) params["repository"] = args.repository;
  if (args.status) params["status"] = args.status;

  const result = await client.get<TriggerListResponse>("/triggers", params);
  if (!result.ok) return formatError(result.error);

  const { triggers, total } = result.data;
  if (triggers.length === 0) {
    return { content: "No trigger rules found." };
  }

  const lines = triggers.map((t: TriggerSummary) =>
    `- **${t.name}** (${t.status})\n  ID: ${t.trigger_id} · Event: ${t.event} · Repo: ${t.repository} · Fired: ${t.fire_count}×`,
  );

  return {
    content: [`## Trigger Rules (${total})`, "", ...lines].join("\n"),
  };
}

// ---------------------------------------------------------------------------
// syn_create_trigger
// ---------------------------------------------------------------------------

export interface CreateTriggerArgs {
  name: string;
  event: string;
  repository: string;
  workflow_id: string;
  conditions?: Record<string, unknown>;
  installation_id?: string;
  input_mapping?: Record<string, string>;
  config?: Record<string, unknown>;
}

export async function synCreateTrigger(
  client: SyntropicClient,
  args: CreateTriggerArgs,
): Promise<{ content: string; isError?: true }> {
  const body: Record<string, unknown> = {
    name: args.name,
    event: args.event,
    repository: args.repository,
    workflow_id: args.workflow_id,
  };
  if (args.conditions) body["conditions"] = args.conditions;
  if (args.installation_id) body["installation_id"] = args.installation_id;
  if (args.input_mapping) body["input_mapping"] = args.input_mapping;
  if (args.config) body["config"] = args.config;

  const result = await client.post<TriggerCreateResponse>("/triggers", body);
  if (!result.ok) return formatError(result.error);

  const t = result.data;
  return {
    content: [
      `## Trigger Created`,
      "",
      `- **Name:** ${t.name}`,
      `- **ID:** ${t.trigger_id}`,
      `- **Status:** ${t.status}`,
      "",
      "The trigger is now active and will fire when matching GitHub events arrive.",
    ].join("\n"),
  };
}

/** Tool definitions for trigger tools. */
export const triggerToolDefs = [
  {
    name: "syn_list_triggers",
    description:
      "List GitHub trigger rules configured on Syntropic137. Triggers automatically start workflows on GitHub events.",
    inputSchema: {
      type: "object" as const,
      properties: {
        repository: { type: "string", description: "Filter by repository (owner/repo)" },
        status: { type: "string", description: "Filter by status (active, paused)" },
      },
    },
  },
  {
    name: "syn_create_trigger",
    description:
      "Create a GitHub trigger rule that automatically starts a workflow when a matching event occurs (e.g., issue opened, PR created).",
    inputSchema: {
      type: "object" as const,
      properties: {
        name: { type: "string", description: "Trigger name" },
        event: {
          type: "string",
          description: "GitHub event type (e.g. 'issues.opened', 'pull_request.opened')",
        },
        repository: { type: "string", description: "Target repository (owner/repo)" },
        workflow_id: { type: "string", description: "Workflow to execute when triggered" },
        conditions: {
          type: "object",
          description: "Additional conditions to match (e.g. label filters)",
        },
        installation_id: {
          type: "string",
          description: "GitHub App installation ID",
        },
        input_mapping: {
          type: "object",
          description: "Map webhook fields to workflow inputs",
          additionalProperties: { type: "string" },
        },
        config: {
          type: "object",
          description: "Additional trigger configuration",
        },
      },
      required: ["name", "event", "repository", "workflow_id"],
    },
  },
] as const;
