import type { SyntropicClient } from "../client.js";
import { formatError } from "../errors.js";
import type { ArtifactListResponse, ArtifactSummary } from "../types.js";
import { formatSize } from "./format.js";

// Re-export extracted artifact detail function for backwards compatibility
export { synGetArtifact } from "./artifact_detail.js";
export type { GetArtifactArgs } from "./artifact_detail.js";

// ---------------------------------------------------------------------------
// syn_list_artifacts
// ---------------------------------------------------------------------------

export interface ListArtifactsArgs {
  workflow_id?: string;
  phase_id?: string;
  artifact_type?: string;
  page?: number;
  page_size?: number;
}

export async function synListArtifacts(
  client: SyntropicClient,
  args: ListArtifactsArgs,
): Promise<{ content: string; isError?: true }> {
  const params: Record<string, string> = {};
  if (args.workflow_id) params["workflow_id"] = args.workflow_id;
  if (args.phase_id) params["phase_id"] = args.phase_id;
  if (args.artifact_type) params["artifact_type"] = args.artifact_type;
  if (args.page) params["page"] = String(args.page);
  if (args.page_size) params["page_size"] = String(args.page_size);

  const result = await client.get<ArtifactListResponse>("/artifacts", params);
  if (!result.ok) return formatError(result.error);

  const { artifacts, total, page, page_size } = result.data;
  if (artifacts.length === 0) {
    return { content: "No artifacts found." };
  }

  const lines = artifacts.map((a: ArtifactSummary) =>
    `- **${a.title ?? a.id}** (${a.artifact_type})\n  ID: ${a.id} · ${formatSize(a.size_bytes)}${a.created_at ? ` · ${a.created_at}` : ""}`,
  );

  // The count used to be `artifacts.length`, which described the page and read
  // as the whole collection - the #1204 defect restated in the agent's own
  // output, where nothing downstream could tell it was truncated.
  return {
    content: [
      `## Artifacts (${total} total, page ${page}/${Math.ceil(total / page_size)})`,
      "",
      ...lines,
    ].join("\n"),
  };
}

/** Tool definitions for artifact tools. */
export const artifactToolDefs = [
  {
    name: "syn_list_artifacts",
    description:
      "List workflow output artifacts. Filter by workflow, phase, or type.",
    inputSchema: {
      type: "object" as const,
      properties: {
        workflow_id: { type: "string", description: "Filter by workflow ID" },
        phase_id: { type: "string", description: "Filter by phase ID" },
        artifact_type: { type: "string", description: "Filter by artifact type" },
        page: { type: "number", description: "Page number (default 1)" },
        page_size: { type: "number", description: "Items per page (default 50, max 200)" },
      },
    },
  },
  {
    name: "syn_get_artifact",
    description:
      "Get a specific artifact including its content. Returns metadata and the artifact body.",
    inputSchema: {
      type: "object" as const,
      properties: {
        artifact_id: { type: "string", description: "Artifact ID" },
      },
      required: ["artifact_id"],
    },
  },
] as const;
