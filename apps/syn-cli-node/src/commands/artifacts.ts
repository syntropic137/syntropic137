/**
 * Artifact commands — list, show, content, create.
 * Port of apps/syn-cli/src/syn_cli/commands/artifacts.py
 */

import { CommandGroup, type CommandDef, type ParsedArgs } from "../framework/command.js";
import { CLIError } from "../framework/errors.js";
import { api, unwrap } from "../client/typed.js";
import type { components } from "../generated/api-types.js";
import { print, printError, printDim } from "../output/console.js";
import { style, BOLD, CYAN, DIM, GREEN } from "../output/ansi.js";
import { formatTimestamp } from "../output/format.js";
import { Table } from "../output/table.js";

type ArtifactSummary = components["schemas"]["ArtifactSummaryResponse"];
type ArtifactDetail = components["schemas"]["ArtifactResponse"];
type ArtifactContent = components["schemas"]["ArtifactContentResponse"];
type CreateArtifact = components["schemas"]["CreateArtifactResponse"];

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
    const items = unwrap<ArtifactSummary[]>(
      await api.GET("/artifacts", {
        params: {
          query: {
            workflow_id: (parsed.values["workflow"] as string | undefined) ?? null,
            phase_id: (parsed.values["phase"] as string | undefined) ?? null,
            artifact_type: (parsed.values["type"] as string | undefined) ?? null,
            limit: Number((parsed.values["limit"] as string | undefined) ?? "50"),
          },
        },
      }),
      "List artifacts",
    );

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

    const a = unwrap<ArtifactDetail>(
      await api.GET("/artifacts/{artifact_id}", {
        params: {
          path: { artifact_id: id },
          query: { include_content: !noContent },
        },
      }),
      "Get artifact",
    );

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

    const data = unwrap<ArtifactContent>(
      await api.GET("/artifacts/{artifact_id}/content", {
        params: { path: { artifact_id: id } },
      }),
      "Get artifact content",
    );
    if (!data.content) { printDim("(no content)"); return; }
    print(data.content);
  },
};

const createCommand: CommandDef = {
  name: "create",
  description: "Create a new artifact",
  options: {
    workflow: { type: "string", short: "w", description: "Workflow ID" },
    type: { type: "string", short: "t", description: "Artifact type (code, markdown, text, json, yaml, research_summary, plan, other)" },
    title: { type: "string", description: "Artifact title" },
    content: { type: "string", short: "c", description: "Artifact content" },
    phase: { type: "string", short: "p", description: "Phase ID" },
  },
  handler: async (parsed: ParsedArgs) => {
    const workflowId = parsed.values["workflow"] as string | undefined;
    const artifactType = parsed.values["type"] as string | undefined;
    const title = parsed.values["title"] as string | undefined;
    const content = parsed.values["content"] as string | undefined;
    const phaseId = parsed.values["phase"] as string | undefined;

    if (!workflowId) { printError("Missing --workflow"); throw new CLIError("Missing option", 1); }
    if (!artifactType) { printError("Missing --type"); throw new CLIError("Missing option", 1); }
    if (!title) { printError("Missing --title"); throw new CLIError("Missing option", 1); }
    if (!content) { printError("Missing --content"); throw new CLIError("Missing option", 1); }

    const data = unwrap<CreateArtifact>(
      await api.POST("/artifacts", {
        body: {
          workflow_id: workflowId,
          artifact_type: artifactType,
          title,
          content,
          content_type: "text/markdown",
          phase_id: phaseId ?? null,
        },
      }),
      "Create artifact",
    );

    print(`${style("Created artifact:", GREEN)} ${style(data.title, CYAN)}`);
    print(`  ID: ${style(data.id, DIM)}`);
    print(`  Type: ${style(data.artifact_type, DIM)}`);
  },
};

export const artifactsGroup = new CommandGroup("artifacts", "Browse and retrieve workflow artifacts");
artifactsGroup.command(listCommand).command(showCommand).command(contentCommand).command(createCommand);
