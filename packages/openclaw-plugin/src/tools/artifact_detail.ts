import type { SyntropicClient } from "../client.js";
import { formatError } from "../errors.js";
import type { ArtifactDetail } from "../types.js";
import { buildMarkdownTable, formatSize } from "./format.js";

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
  const rows: [string, string][] = [
    ["ID", a.id],
    ["Type", a.artifact_type],
    ["Content Type", a.content_type],
    ["Size", formatSize(a.size_bytes)],
    ["Primary", a.is_primary_deliverable ? "Yes" : "No"],
  ];
  if (a.created_at) rows.push(["Created", a.created_at]);
  if (a.created_by) rows.push(["Created By", a.created_by]);
  if (a.derived_from.length > 0) rows.push(["Derived From", a.derived_from.join(", ")]);

  const sections = [...buildMarkdownTable(`Artifact: ${a.title ?? a.id}`, rows)];

  if (a.content) {
    const preview = a.content.length > 2000
      ? a.content.slice(0, 2000) + "\n\n... (truncated)"
      : a.content;
    sections.push("", "### Content", "", preview);
  }

  return { content: sections.join("\n") };
}
