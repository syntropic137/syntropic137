import type { SyntropicClient } from "../client.js";
import { formatError } from "../errors.js";
import type { ArtifactDetail, ArtifactSummary } from "../types.js";

// ---------------------------------------------------------------------------
// syn_list_artifacts
// ---------------------------------------------------------------------------

export interface ListArtifactsArgs {
  workflow_id?: string;
  phase_id?: string;
  artifact_type?: string;
  limit?: number;
}

export async function synListArtifacts(
  client: SyntropicClient,
  args: ListArtifactsArgs,
): Promise<{ content: string; isError?: true }> {
  const params: Record<string, string> = {};
  if (args.workflow_id) params["workflow_id"] = args.workflow_id;
  if (args.phase_id) params["phase_id"] = args.phase_id;
  if (args.artifact_type) params["artifact_type"] = args.artifact_type;
  if (args.limit) params["limit"] = String(args.limit);

  const result = await client.get<ArtifactSummary[]>("/artifacts", params);
  if (!result.ok) return formatError(result.error);

  const artifacts = result.data;
  if (artifacts.length === 0) {
    return { content: "No artifacts found." };
  }

  const lines = artifacts.map((a: ArtifactSummary) => {
    const size = a.size_bytes > 1024
      ? `${(a.size_bytes / 1024).toFixed(1)} KB`
      : `${a.size_bytes} bytes`;
    return `- **${a.title ?? a.id}** (${a.artifact_type})\n  ID: ${a.id} · ${size}${a.created_at ? ` · ${a.created_at}` : ""}`;
  });

  return {
    content: [`## Artifacts (${artifacts.length})`, "", ...lines].join("\n"),
  };
}

// ---------------------------------------------------------------------------
// syn_get_artifact
// ---------------------------------------------------------------------------

export interface GetArtifactArgs {
  artifact_id: string;
}

export async function synGetArtifact(
  client: SyntropicClient,
  args: GetArtifactArgs,
): Promise<{ content: string; isError?: true }> {
  const result = await client.get<ArtifactDetail>(
    `/artifacts/${encodeURIComponent(args.artifact_id)}`,
    { include_content: "true" },
  );
  if (!result.ok) return formatError(result.error);

  const a = result.data;
  const size = a.size_bytes > 1024
    ? `${(a.size_bytes / 1024).toFixed(1)} KB`
    : `${a.size_bytes} bytes`;

  const sections = [
    `## Artifact: ${a.title ?? a.id}`,
    "",
    `| Field | Value |`,
    `|-------|-------|`,
    `| ID | ${a.id} |`,
    `| Type | ${a.artifact_type} |`,
    `| Content Type | ${a.content_type} |`,
    `| Size | ${size} |`,
    `| Primary | ${a.is_primary_deliverable ? "Yes" : "No"} |`,
  ];

  if (a.created_at) sections.push(`| Created | ${a.created_at} |`);
  if (a.created_by) sections.push(`| Created By | ${a.created_by} |`);
  if (a.derived_from.length > 0) sections.push(`| Derived From | ${a.derived_from.join(", ")} |`);

  if (a.content) {
    const preview = a.content.length > 2000
      ? a.content.slice(0, 2000) + "\n\n... (truncated)"
      : a.content;
    sections.push("", "### Content", "", preview);
  }

  return { content: sections.join("\n") };
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
        limit: { type: "number", description: "Max results (default 200)" },
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
