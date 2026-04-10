/**
 * Workflow CRUD commands — create, list, show, validate, delete.
 * Port of apps/syn-cli/src/syn_cli/commands/workflow/_crud.py
 */

import type { CommandDef, ParsedArgs } from "../../framework/command.js";
import { CLIError } from "../../framework/errors.js";
import { api, unwrap } from "../../client/typed.js";
import type { components } from "../../generated/api-types.js";
import { printError, printSuccess, print, printDim } from "../../output/console.js";
import { style, BOLD, CYAN, DIM, GREEN, YELLOW } from "../../output/ansi.js";
import { Table } from "../../output/table.js";
import { resolveWorkflow } from "./resolver.js";
import { detectFormat, resolvePackage } from "../../packages/resolver.js";
import fs from "node:fs";
import path from "node:path";

type WorkflowResponse = components["schemas"]["WorkflowResponse"];

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
    repos: { type: "string", short: "R", description: "Default GitHub URLs for workspace hydration (repeatable). ADR-058.", multiple: true },
    from: { type: "string", short: "f", description: "Path to workflow.yaml or directory containing it — registers phases from YAML" },
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
    const reposValues = parsed.values["repos"];
    const templateRepos: string[] = Array.isArray(reposValues) ? reposValues as string[] : reposValues ? [reposValues as string] : [];
    const fromPath = parsed.values["from"] as string | undefined;

    let phases: Record<string, unknown>[] | undefined;
    let inputDeclarations: unknown[] | undefined;

    if (fromPath) {
      const resolved = path.resolve(fromPath);
      if (!fs.existsSync(resolved)) {
        printError(`Path not found: ${fromPath}`);
        throw new CLIError("Path not found", 1);
      }
      const stat = fs.statSync(resolved);
      const workflowDir = stat.isDirectory() ? resolved : path.dirname(resolved);
      try {
        const { workflows } = resolvePackage(workflowDir);
        if (workflows.length === 0) {
          printError(`No workflows found in: ${workflowDir}`);
          throw new CLIError("No workflows found", 1);
        }
        const wf = workflows[0]!;
        phases = wf.phases as Record<string, unknown>[];
        inputDeclarations = wf.input_declarations;
      } catch (err) {
        if (err instanceof CLIError) throw err;
        printError(`Failed to parse workflow YAML: ${err instanceof Error ? err.message : String(err)}`);
        throw new CLIError("YAML parse error", 1);
      }
    }

    const data = unwrap(
      await api.POST("/workflows", {
        body: {
          name,
          workflow_type: workflowType,
          classification: "standard",
          repository_url: repoUrl,
          repository_ref: repoRef,
          description: description ?? null,
          ...(templateRepos.length > 0 ? { repos: templateRepos } : {}),
          ...(phases !== undefined ? { phases } : {}),
          ...(inputDeclarations !== undefined ? { input_declarations: inputDeclarations } : {}),
        },
      }),
      "Failed to create workflow",
    );

    const workflowId = data.id;
    printSuccess(`Created workflow: ${style(name, CYAN)}`);
    print(`  ID: ${style(workflowId, DIM)}`);
    print(`  Type: ${style(workflowType, DIM)}`);
    if (!fromPath) {
      printDim(`  Tip: Use --from ./workflow.yaml to register phases from a YAML file`);
    }
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

    const data = unwrap(
      await api.GET("/workflows", {
        params: { query: { include_archived: includeArchived } },
      }),
      "Failed to list workflows",
    );
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
        w.id.slice(0, 12) + "...",
        w.name,
        w.workflow_type,
        String(w.phase_count),
      );
    }
    table.print();
  },
};

// ---------------------------------------------------------------------------
// show
// ---------------------------------------------------------------------------

function renderInputDeclarations(declarations: WorkflowResponse["input_declarations"]): void {
  const items = declarations ?? [];
  if (items.length === 0) return;
  print(`\n  ${style("Inputs:", BOLD)}`);
  for (const d of items) {
    const req = d.required ? style("required", YELLOW) : style("optional", DIM);
    const desc = d.description ? ` — ${d.description}` : "";
    const def = d.default != null ? ` (default: ${d.default})` : "";
    print(`    ${style(d.name, GREEN)} [${req}]${desc}${def}`);
  }
}

function renderWorkflowDetail(detail: WorkflowResponse): void {
  print("");
  print(style("Workflow Details", BOLD));
  print(`  ${style("ID:", DIM)} ${detail.id}`);
  print(`  ${style("Name:", DIM)} ${style(detail.name, CYAN)}`);
  print(`  ${style("Type:", DIM)} ${detail.workflow_type}`);
  print(`  ${style("Classification:", DIM)} ${detail.classification}`);
  const phases = detail.phases ?? [];
  if (phases.length > 0) {
    print(`\n  ${style(`Phases (${phases.length}):`, BOLD)}`);
    for (const phase of phases) {
      print(`    - ${phase.name ?? "unnamed"}`);
    }
  } else {
    printDim("  No phases defined");
  }
  renderInputDeclarations(detail.input_declarations);
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
    const data = unwrap(
      await api.GET("/workflows/{workflow_id}", {
        params: { path: { workflow_id: wf.id } },
      }),
      "Failed to get workflow",
    );
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
    const data = unwrap(
      await api.POST("/workflows/validate", {
        body: { content, filename: path.basename(file) },
      }),
      "Failed to validate workflow",
    );

    if (data.valid) {
      printSuccess("Valid workflow definition\n");
      print(`  ${style("Name:", DIM)} ${data.name}`);
      print(`  ${style("Type:", DIM)} ${data.workflow_type}`);
      print(`  ${style("Phases:", DIM)} ${String(data.phase_count)}`);
    } else {
      printError("Invalid workflow definition");
      if (data.errors) {
        for (const error of data.errors) {
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

    unwrap(
      await api.DELETE("/workflows/{workflow_id}", {
        params: { path: { workflow_id: wf.id } },
      }),
      "Failed to archive workflow",
    );
    printSuccess(`Archived workflow: ${style(wf.name, CYAN)}`);
    print(`  ID: ${style(wf.id, DIM)}`);
  },
};
