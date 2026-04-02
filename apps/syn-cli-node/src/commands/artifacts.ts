/**
 * Artifact commands — list, show, content, create.
 * Port of apps/syn-cli/src/syn_cli/commands/artifacts.py
 */

import { CommandGroup, type CommandDef, type ParsedArgs } from "../framework/command.js";
import { CLIError } from "../framework/errors.js";
import { apiGet, apiGetList, apiPost, buildParams } from "../client/api.js";
import { print, printError, printDim } from "../output/console.js";
import { style, BOLD, CYAN, DIM, GREEN } from "../output/ansi.js";
import { formatTimestamp } from "../output/format.js";
import { Table } from "../output/table.js";
import type {
  ArtifactSummaryResponse,
  ArtifactResponse,
  ArtifactContentResponse,
  CreateArtifactResponse,
} from "../generated/types.js";

const listCommand: CommandDef = {
  name: "list",
  description: "List artifacts",
  options: {
    workflow: { type: "string", short: "w", description: "Filter by workflow ID" },
    phase: { type: "string", short: "p", description: "Filter by phase ID" },
    type: { type: "string", short: "t", description: "Filter by artifact type" },
    limit: { type: "string", description: "Max results (max 200)", default: "50" },
  },
  handler: async (parsed: ParsedArgs) => {
    const params = buildParams({
      workflow_id: (parsed.values["workflow"] as string | undefined) ?? null,
      phase_id: (parsed.values["phase"] as string | undefined) ?? null,
      artifact_type: (parsed.values["type"] as string | undefined) ?? null,
      limit: (parsed.values["limit"] as string | undefined) ?? "50",
    });
    const items = await apiGetList<ArtifactSummaryResponse>("/artifacts", { params });

    if (items.length === 0) { printDim("No artifacts found."); return; }

    const table = new Table({ title: "Artifacts" });
    table.addColumn("ID", { style: CYAN });
    table.addColumn("Type");
    table.addColumn("Title");
    table.addColumn("Size", { align: "right" });
    table.addColumn("Created");

    for (const a of items) {
      const size = a.size_bytes;
      const sizeStr = size < 1024 ? `${size}B` : `${Math.floor(size / 1024)}KB`;
      table.addRow(
        a.id.slice(0, 12),
        a.artifact_type,
        a.title ?? "\u2014",
        sizeStr,
        formatTimestamp(a.created_at),
      );
    }
    table.print();
  },
};

const showCommand: CommandDef = {
  name: "show",
  description: "Show artifact metadata and content",
  args: [{ name: "artifact-id", description: "Artifact ID", required: true }],
  options: {
    "no-content": { type: "boolean", description: "Skip content; show metadata only", default: false },
  },
  handler: async (parsed: ParsedArgs) => {
    const id = parsed.positionals[0];
    if (!id) { printError("Missing artifact-id"); throw new CLIError("Missing argument", 1); }
    const noContent = parsed.values["no-content"] === true;

    const a = await apiGet<ArtifactResponse>(`/artifacts/${id}`, {
      params: { include_content: String(!noContent) },
    });

    print(`${style("Artifact:", BOLD)} ${a.id}`);
    print(`  Type:    ${a.artifact_type}`);
    if (a.title) print(`  Title:   ${a.title}`);
    if (a.workflow_id) print(`  Workflow: ${a.workflow_id}`);
    if (a.phase_id) print(`  Phase:   ${a.phase_id}`);
    print(`  Created: ${formatTimestamp(a.created_at)}`);
    if (a.size_bytes) print(`  Size:    ${a.size_bytes.toLocaleString()} bytes`);

    if (!noContent && a.content) {
      print("");
      print(a.content);
    }
  },
};

const contentCommand: CommandDef = {
  name: "content",
  description: "Print the raw content of an artifact",
  args: [{ name: "artifact-id", description: "Artifact ID", required: true }],
  handler: async (parsed: ParsedArgs) => {
    const id = parsed.positionals[0];
    if (!id) { printError("Missing artifact-id"); throw new CLIError("Missing argument", 1); }

    const data = await apiGet<ArtifactContentResponse>(`/artifacts/${id}/content`);
    if (!data.content) { printDim("(no content)"); return; }
    print(data.content);
  },
};

const createCommand: CommandDef = {
  name: "create",
  description: "Create a new artifact",
  options: {
    workflow: { type: "string", short: "w", description: "Workflow ID" },
    type: { type: "string", short: "t", description: "Artifact type (code, document, research_summary)" },
    title: { type: "string", description: "Artifact title" },
    content: { type: "string", short: "c", description: "Artifact content" },
    phase: { type: "string", short: "p", description: "Phase ID" },
  },
  handler: async (parsed: ParsedArgs) => {
    const data = await apiPost<CreateArtifactResponse>("/artifacts", {
      body: {
        workflow_id: (parsed.values["workflow"] as string | undefined) ?? null,
        artifact_type: (parsed.values["type"] as string | undefined) ?? null,
        title: (parsed.values["title"] as string | undefined) ?? null,
        content: (parsed.values["content"] as string | undefined) ?? null,
        phase_id: (parsed.values["phase"] as string | undefined) ?? null,
      },
    });

    print(`${style("Created artifact:", GREEN)} ${style(data.title, CYAN)}`);
    print(`  ID: ${style(data.id, DIM)}`);
    print(`  Type: ${style(data.artifact_type, DIM)}`);
  },
};

export const artifactsGroup = new CommandGroup("artifacts", "Browse and retrieve workflow artifacts");
artifactsGroup.command(listCommand).command(showCommand).command(contentCommand).command(createCommand);
