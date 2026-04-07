/**
 * Workflow run and status commands.
 * Port of apps/syn-cli/src/syn_cli/commands/workflow/_run.py
 */

import type { CommandDef, ParsedArgs } from "../../framework/command.js";
import { CLIError } from "../../framework/errors.js";
import { api, unwrap } from "../../client/typed.js";
import { printError, printSuccess, print, printDim } from "../../output/console.js";
import { style, BOLD, CYAN, DIM, GREEN, YELLOW } from "../../output/ansi.js";
import { formatCost, formatTokens } from "../../output/format.js";
import { Table } from "../../output/table.js";
import { resolveWorkflow } from "./resolver.js";
import { parseInputs } from "./models.js";

// ---------------------------------------------------------------------------
// run
// ---------------------------------------------------------------------------

function displayRunPreview(
  workflowName: string,
  fullId: string,
  phaseCount: number,
  task: string | undefined,
  parsedInputs: Record<string, string | number | boolean>,
): void {
  print("");
  print(style("Workflow Execution", CYAN));
  print(`  ${style(workflowName, BOLD)}`);
  print(`  ${style(`ID: ${fullId}`, DIM)}`);
  print(`  ${style(`Phases: ${phaseCount}`, DIM)}`);

  if (task) {
    print(`\n${style("Task:", BOLD)} ${style(task, GREEN)}`);
  }

  const inputEntries = Object.entries(parsedInputs);
  if (inputEntries.length > 0) {
    print(`\n${style("Inputs:", BOLD)}`);
    for (const [key, value] of inputEntries) {
      print(`  ${key}: ${style(String(value), GREEN)}`);
    }
  }
}

export const runCommand: CommandDef = {
  name: "run",
  description: "Execute a workflow",
  args: [{ name: "workflow-id", description: "Workflow ID (partial match supported)", required: true }],
  options: {
    input: { type: "string", short: "i", description: "Input variables as key=value", multiple: true },
    task: { type: "string", short: "t", description: "Primary task description ($ARGUMENTS)" },
    "dry-run": { type: "boolean", short: "n", description: "Validate without executing", default: false },
    quiet: { type: "boolean", short: "q", description: "Minimal output", default: false },
  },
  handler: async (parsed: ParsedArgs) => {
    const partialId = parsed.positionals[0];
    if (!partialId) {
      printError("Missing required argument: workflow-id");
      throw new CLIError("Missing argument", 1);
    }

    const inputValues = parsed.values["input"];
    const inputs = Array.isArray(inputValues) ? inputValues as string[] : undefined;
    const parsedInputs = parseInputs(inputs);
    const task = parsed.values["task"] as string | undefined;
    const dryRun = parsed.values["dry-run"] === true;
    const quiet = parsed.values["quiet"] === true;

    const wf = await resolveWorkflow(partialId);

    if (!quiet) {
      displayRunPreview(wf.name, wf.id, wf.phase_count, task, parsedInputs);
    }

    if (dryRun) {
      print(`\n${style("DRY RUN", YELLOW)} - Workflow is valid and ready to execute`);
      printDim("Remove --dry-run to execute");
      return;
    }

    const result = unwrap(
      await api.POST("/workflows/{workflow_id}/execute", {
        params: { path: { workflow_id: wf.id } },
        body: {
          inputs: Object.fromEntries(
            Object.entries(parsedInputs).map(([k, v]) => [k, String(v)]),
          ),
          task: task ?? null,
          provider: "claude",
        },
      }),
      "Failed to execute workflow",
    );

    if (result.status === "started") {
      printSuccess("\nWorkflow execution started");
      print(`  Execution ID: ${result.execution_id}`);
    } else {
      print(`\n${style(`Status: ${result.status}`, YELLOW)}`);
    }
  },
};

// ---------------------------------------------------------------------------
// status
// ---------------------------------------------------------------------------

export const statusCommand: CommandDef = {
  name: "status",
  description: "Show execution history for a workflow",
  args: [{ name: "workflow-id", description: "Workflow ID (partial match supported)", required: true }],
  handler: async (parsed: ParsedArgs) => {
    const partialId = parsed.positionals[0];
    if (!partialId) {
      printError("Missing required argument: workflow-id");
      throw new CLIError("Missing argument", 1);
    }

    const wf = await resolveWorkflow(partialId);

    print("");
    print(style("Workflow Status", CYAN));
    print(`  ${style(wf.name, BOLD)}`);
    print(`  ${style(`ID: ${wf.id}`, DIM)}`);

    const data = unwrap(
      await api.GET("/workflows/{workflow_id}/runs", {
        params: { path: { workflow_id: wf.id } },
      }),
      "Failed to list workflow runs",
    );
    const runs = data.runs ?? [];

    if (runs.length === 0) {
      printDim("\nNo executions found.");
      printDim(`Run with: syn workflow run ${partialId}`);
      return;
    }

    const table = new Table({ title: "Executions" });
    table.addColumn("ID", { style: DIM });
    table.addColumn("Status");
    table.addColumn("Phases", { align: "right" });
    table.addColumn("Tokens", { align: "right" });
    table.addColumn("Cost", { align: "right" });

    for (const run of runs) {
      table.addRow(
        run.workflow_execution_id.slice(0, 12) + "...",
        run.status,
        `${run.completed_phases}/${run.total_phases}`,
        formatTokens(run.total_tokens),
        formatCost(run.total_cost_usd),
      );
    }
    table.print();
  },
};
