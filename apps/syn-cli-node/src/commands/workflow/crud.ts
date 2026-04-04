/**
 * Workflow CRUD commands — create, list, show, validate, delete.
 * Port of apps/syn-cli/src/syn_cli/commands/workflow/_crud.py
 */

import type { CommandDef, ParsedArgs } from "../../framework/command.js";
import { CLIError } from "../../framework/errors.js";
import { apiGet, apiPost, apiDelete } from "../../client/api.js";
import { printError, printSuccess, print, printDim } from "../../output/console.js";
import { style, BOLD, CYAN, DIM, GREEN } from "../../output/ansi.js";
import { Table } from "../../output/table.js";
import { resolveWorkflow } from "./resolver.js";
import type { WorkflowDetail } from "./models.js";
import { detectFormat, resolvePackage } from "../../packages/resolver.js";
import path from "node:path";

// ---------------------------------------------------------------------------
// create
// ---------------------------------------------------------------------------

export const createCommand: CommandDef = {
  name: "create",
  description: "Create a new workflow",
  args: [{ name: "name", description: "Name of the workflow", required: true }],
  options: {
    type: { type: "string", short: "t", description: "Workflow type (research, planning, implementation, review, deployment, custom)", default: "custom" },
    repo: { type: "string", short: "r", description: "Repository URL", default: "https://github.com/example/repo" },
    ref: { type: "string", description: "Repository ref/branch", default: "main" },
    description: { type: "string", short: "d", description: "Workflow description" },
  },
  handler: async (parsed: ParsedArgs) => {
    const name = parsed.positionals[0];
    if (!name) {
      printError("Missing required argument: name");
      throw new CLIError("Missing argument", 1);
    }

    const workflowType = (parsed.values["type"] as string | undefined) ?? "custom";
    const repoUrl = (parsed.values["repo"] as string | undefined) ?? "https://github.com/example/repo";
    const repoRef = (parsed.values["ref"] as string | undefined) ?? "main";
    const description = parsed.values["description"] as string | undefined;

    const data = await apiPost<Record<string, unknown>>("/workflows", {
      body: {
        name,
        workflow_type: workflowType,
        repository_url: repoUrl,
        repository_ref: repoRef,
        description: description ?? null,
      },
    });

    const workflowId = String(data["id"] ?? data["workflow_id"] ?? "unknown");
    printSuccess(`Created workflow: ${style(name, CYAN)}`);
    print(`  ID: ${style(workflowId, DIM)}`);
    print(`  Type: ${style(workflowType, DIM)}`);
  },
};

// ---------------------------------------------------------------------------
// list
// ---------------------------------------------------------------------------

export const listCommand: CommandDef = {
  name: "list",
  description: "List all workflows",
  options: {
    "include-archived": { type: "boolean", description: "Include archived workflows", default: false },
  },
  handler: async (parsed: ParsedArgs) => {
    const includeArchived = parsed.values["include-archived"] === true;
    const params: Record<string, string> = {};
    if (includeArchived) params["include_archived"] = "true";

    const data = await apiGet<{ workflows: Record<string, unknown>[] }>("/workflows", { params });
    const workflows = data.workflows ?? [];

    if (workflows.length === 0) {
      printDim("No workflows found. Create one with:");
      print(`  ${style('syn workflow create "My Workflow"', CYAN)}`);
      return;
    }

    const table = new Table({ title: "Workflows" });
    table.addColumn("ID", { style: DIM });
    table.addColumn("Name", { style: CYAN });
    table.addColumn("Type", { style: GREEN });
    table.addColumn("Phases", { align: "right" });

    for (const w of workflows) {
      table.addRow(
        String(w["id"] ?? "").slice(0, 12) + "...",
        String(w["name"] ?? ""),
        String(w["workflow_type"] ?? ""),
        String(w["phase_count"] ?? 0),
      );
    }
    table.print();
  },
};

// ---------------------------------------------------------------------------
// show
// ---------------------------------------------------------------------------

function renderWorkflowDetail(detail: WorkflowDetail): void {
  print("");
  print(style("Workflow Details", BOLD));
  print(`  ${style("ID:", DIM)} ${detail.id}`);
  print(`  ${style("Name:", DIM)} ${style(detail.name, CYAN)}`);
  print(`  ${style("Type:", DIM)} ${detail.workflow_type}`);
  print(`  ${style("Classification:", DIM)} ${detail.classification}`);
  if (detail.phases.length > 0) {
    print(`\n  ${style(`Phases (${detail.phases.length}):`, BOLD)}`);
    for (const phase of detail.phases) {
      print(`    - ${String((phase as Record<string, unknown>)["name"] ?? "unnamed")}`);
    }
  } else {
    printDim("  No phases defined");
  }
}

export const showCommand: CommandDef = {
  name: "show",
  description: "Show details of a workflow",
  args: [{ name: "workflow-id", description: "Workflow ID (partial match supported)", required: true }],
  handler: async (parsed: ParsedArgs) => {
    const partialId = parsed.positionals[0];
    if (!partialId) {
      printError("Missing required argument: workflow-id");
      throw new CLIError("Missing argument", 1);
    }

    const wf = await resolveWorkflow(partialId);
    const data = await apiGet<WorkflowDetail>(`/workflows/${wf.id}`);
    renderWorkflowDetail(data);
  },
};

// ---------------------------------------------------------------------------
// validate
// ---------------------------------------------------------------------------

export const validateCommand: CommandDef = {
  name: "validate",
  description: "Validate a workflow YAML file or package directory",
  args: [{ name: "file", description: "YAML file or package directory", required: true }],
  handler: async (parsed: ParsedArgs) => {
    const file = parsed.positionals[0];
    if (!file) {
      printError("Missing required argument: file");
      throw new CLIError("Missing argument", 1);
    }

    const fs = await import("node:fs");
    const stat = fs.statSync(file);

    if (stat.isDirectory()) {
      validatePackageDir(file);
      return;
    }

    const content = fs.readFileSync(file, "utf-8");
    const data = await apiPost<Record<string, unknown>>("/workflows/validate", {
      body: { content, filename: path.basename(file) },
    });

    if (data["valid"]) {
      printSuccess("Valid workflow definition\n");
      print(`  ${style("Name:", DIM)} ${String(data["name"] ?? "")}`);
      print(`  ${style("Type:", DIM)} ${String(data["workflow_type"] ?? "")}`);
      print(`  ${style("Phases:", DIM)} ${String(data["phase_count"] ?? 0)}`);
    } else {
      printError("Invalid workflow definition");
      const errors = data["errors"] as string[] | undefined;
      if (errors) {
        for (const error of errors) {
          print(`  ${error}`);
        }
      }
      throw new CLIError("Validation failed", 1);
    }
  },
};

function validatePackageDir(pkgPath: string): void {
  try {
    const fmt = detectFormat(pkgPath);
    const { workflows } = resolvePackage(pkgPath);

    printSuccess(`Valid ${fmt} package\n`);
    print(`  ${style("Directory:", DIM)} ${pkgPath}`);
    print(`  ${style("Workflows:", DIM)} ${workflows.length}`);
    const totalPhases = workflows.reduce((sum, wf) => sum + wf.phases.length, 0);
    print(`  ${style("Total phases:", DIM)} ${totalPhases}`);
    for (const wf of workflows) {
      printDim(`    \u2022 ${wf.name} (${wf.phases.length} phases)`);
    }
  } catch (err) {
    printError(err instanceof Error ? err.message : String(err));
    throw new CLIError("Validation failed", 1);
  }
}

// ---------------------------------------------------------------------------
// delete
// ---------------------------------------------------------------------------

export const deleteCommand: CommandDef = {
  name: "delete",
  description: "Archive (soft-delete) a workflow",
  args: [{ name: "workflow-id", description: "Workflow ID (partial match supported)", required: true }],
  options: {
    force: { type: "boolean", short: "f", description: "Skip confirmation prompt", default: false },
  },
  handler: async (parsed: ParsedArgs) => {
    const partialId = parsed.positionals[0];
    if (!partialId) {
      printError("Missing required argument: workflow-id");
      throw new CLIError("Missing argument", 1);
    }

    const force = parsed.values["force"] === true;
    const wf = await resolveWorkflow(partialId, { includeArchived: true });

    if (!force) {
      // In non-interactive CLI, require --force
      printError(`Use --force to confirm archiving '${wf.name}' (${wf.id})`);
      throw new CLIError("Confirmation required", 1);
    }

    await apiDelete(`/workflows/${wf.id}`);
    printSuccess(`Archived workflow: ${style(wf.name, CYAN)}`);
    print(`  ID: ${style(wf.id, DIM)}`);
  },
};
