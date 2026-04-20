/**
 * Workflow run and status commands.
 * Port of apps/syn-cli/src/syn_cli/commands/workflow/_run.py
 */

import type { CommandDef, ParsedArgs } from "../../framework/command.js";
import { CLIError } from "../../framework/errors.js";
import { api, unwrap } from "../../client/typed.js";
import { printError, printSuccess, print, printDim } from "../../output/console.js";
import { style, BOLD, CYAN, DIM, GREEN, RED, YELLOW } from "../../output/ansi.js";
import { formatCost, formatTokens } from "../../output/format.js";
import { Table } from "../../output/table.js";
import { resolveWorkflow } from "./resolver.js";
import { parseInputs } from "./models.js";
import type { components } from "../../generated/api-types.js";

type InputDeclaration = components["schemas"]["InputDeclarationModel"];

/**
 * Resolve each -R value into a form the API accepts (owner/repo or full URL).
 * `repo-*` values are looked up via the repos API and substituted with
 * `full_name`, so users can paste `syn repo list` IDs directly.
 */
export async function resolveRepoRefs(refs: string[]): Promise<string[]> {
  const out: string[] = [];
  for (const ref of refs) {
    if (/^repo-[a-z0-9]+$/i.test(ref)) {
      const repo = unwrap(
        await api.GET("/repos/{repo_id}", {
          params: { path: { repo_id: ref } },
        }),
        `Failed to resolve ${ref}`,
      );
      if (!repo.full_name) {
        throw new CLIError(`Repo ${ref} has no full_name; deregister and re-register`, 1);
      }
      out.push(repo.full_name);
    } else {
      out.push(ref);
    }
  }
  return out;
}

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
    repo: { type: "string", short: "R", description: "Repository to pre-clone (repeatable). Accepts owner/repo, full GitHub URL, or syn repo-* ID.", multiple: true },
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
    const repoValues = parsed.values["repo"];
    const rawRepos: string[] = Array.isArray(repoValues) ? repoValues as string[] : repoValues ? [repoValues as string] : [];
    const dryRun = parsed.values["dry-run"] === true;
    const quiet = parsed.values["quiet"] === true;

    // ADR-063: repositories are a typed channel, not smuggled via `--input`.
    // Fail loud at the CLI so users see the migration path immediately instead of
    // the API's 422 (which is also wired up for belt-and-suspenders).
    const leakedKeys = ["repos", "repository"].filter((k) => Object.hasOwn(parsedInputs, k));
    if (leakedKeys.length > 0) {
      const quoted = leakedKeys.map((k) => `'${k}'`).join(", ");
      printError(`${quoted} is not a valid --input key.`);
      printDim("Use -R <owner/repo> (repeatable) to specify repositories at execution time.");
      throw new CLIError("Invalid input key", 1);
    }

    // Accept both `owner/repo` (and full GitHub URLs) and syn internal `repo-*` IDs.
    // Resolve `repo-*` via the repos API so users can paste `syn repo list` output directly.
    const repos = await resolveRepoRefs(rawRepos);

    const wf = await resolveWorkflow(partialId);

    // Fetch full workflow detail to check input declarations
    const detail = unwrap(
      await api.GET("/workflows/{workflow_id}", {
        params: { path: { workflow_id: wf.id } },
      }),
      "Failed to get workflow details",
    );

    const declarations: InputDeclaration[] = detail.input_declarations ?? [];
    const missingRequired = declarations.filter(
      (d) => d.required && d.default == null && !Object.hasOwn(parsedInputs, d.name),
    );
    if (missingRequired.length > 0) {
      printError("Missing required inputs:");
      for (const d of missingRequired) {
        const desc = d.description ? ` — ${d.description}` : "";
        print(`  ${style(`--input ${d.name}=<value>`, RED)}${desc}`);
      }
      print("");
      printDim("Provide all required inputs to run this workflow.");
      throw new CLIError("Missing required inputs", 1);
    }

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
          ...(repos.length > 0 ? { repos } : {}),
          provider: "claude",
        },
      }),
      "Failed to execute workflow",
    );

    if (result.status === "started" && result.execution_id?.startsWith("exec-")) {
      printSuccess("\nWorkflow execution started");
      print(`  Execution ID: ${result.execution_id}`);
    } else {
      printError(`\nUnexpected server response: status=${result.status} execution_id=${result.execution_id ?? "<none>"}`);
      throw new CLIError("Workflow execution did not start", 1);
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
