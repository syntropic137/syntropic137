/**
 * Workflow run and status commands.
 * Port of apps/syn-cli/src/syn_cli/commands/workflow/_run.py
 */

import type { CommandDef, ParsedArgs } from "../../framework/command.js";
import { CLIError } from "../../framework/errors.js";
import { api, unwrap } from "../../client/typed.js";
import { printError, print, printDim } from "../../output/console.js";
import { printStarted } from "../../output/started.js";
import { style, BOLD, CYAN, DIM, GREEN, RED, YELLOW } from "../../output/ansi.js";
import { formatCost, formatTokens } from "../../output/format.js";
import { Table } from "../../output/table.js";
import { resolveWorkflow } from "./resolver.js";
import { parseInputs } from "./models.js";
import type { components } from "../../generated/api-types.js";

type InputDeclaration = components["schemas"]["InputDeclarationModel"];
type PhaseDefinition = components["schemas"]["PhaseDefinitionResponse"];

/**
 * The input name `-t` supplies. The API merges the top-level `task` field into
 * `inputs` as `inputs["task"]`, so `$ARGUMENTS` and `{{task}}` are two
 * spellings of one value (docs/api/v1/workflows.md "Prompt Substitution";
 * `_substitute_inputs` layers 2a and 2d). Both directions of this file's
 * deliverability checks depend on knowing that, so the name is written once.
 */
const TASK_INPUT_NAME = "task";

/**
 * Input names any phase prompt in this workflow can actually consume, in either
 * spelling: `{{name}}` for any name, plus `$ARGUMENTS` for `task`. A supplied
 * name outside this set is substituted into nothing and silently discarded
 * (issues #1081, #1280).
 *
 * Callers ask whether the workflow consumes a name; which spelling answered is
 * not their business.
 */
function consumedInputNames(phases: PhaseDefinition[] | undefined): Set<string> {
  const consumed = new Set<string>();
  for (const phase of phases ?? []) {
    const template = phase.prompt_template ?? "";
    for (const match of template.matchAll(/\{\{(\w+)\}\}/g)) {
      consumed.add(match[1]!);
    }
    if (template.includes("$ARGUMENTS")) {
      consumed.add(TASK_INPUT_NAME);
    }
  }
  return consumed;
}

/**
 * Whether the workflow declares a default for `name`, which the API applies when
 * the dispatch supplies no value of its own (`_merge_inputs`). Such a name is
 * never empty at render time, so it needs no warning.
 */
function declaredDefault(declarations: InputDeclaration[], name: string): boolean {
  return declarations.some((d) => d.name === name && d.default != null);
}

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

    // Input names this dispatch supplies a value for. `-t` supplies
    // TASK_INPUT_NAME just as surely as `-i task=...` does, so a workflow that
    // declares `task` as a required input must not be reported as missing it
    // when the caller typed `-t` (#1280).
    const supplied = new Set(Object.keys(parsedInputs));
    if (task !== undefined) {
      supplied.add(TASK_INPUT_NAME);
    }

    const missingRequired = declarations.filter(
      (d) => d.required && d.default == null && !supplied.has(d.name),
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

    // Dispatch-time deliverability checks (issues #1081, #1280): all of them are
    // purely local — the workflow detail already fetched above has
    // everything needed — and must fire on the --dry-run path too, since
    // dry-run's job is to answer "will this do what I typed?".
    const consumed = consumedInputNames(detail.phases);
    for (const key of Object.keys(parsedInputs)) {
      if (!consumed.has(key)) {
        print(
          style("Warning:", YELLOW) +
            ` --input '${key}' is not referenced by any phase prompt in '${wf.name}' — it will be discarded.`,
        );
      }
    }
    if (repos.length > 0 && !detail.requires_repos) {
      print(
        style("Warning:", YELLOW) +
          ` '${wf.name}' has requires_repos: false — -R repos will not be cloned.`,
      );
    }

    // A prompt that consumes `task` and a dispatch that supplies one are two
    // independent facts, and either one alone used to dispatch silently (#1280).
    // They are not equally bad, which is why one refuses and the one above it
    // only warns:
    //
    //   -t with nothing to consume it REFUSES. An unreferenced --input is one
    //   parameter of several going missing; a discarded -t is the entire
    //   instruction going missing, and what runs instead is the workflow's own
    //   hardcoded prompt. The run then costs full money and time and reports
    //   success for work nobody asked for. There is no dispatch for which that
    //   is the intended outcome, so there is nothing to preserve by continuing.
    //   The remedy is in the caller's hands either way: drop -t, or make a phase
    //   consume it.
    //
    //   `$ARGUMENTS` with no task WARNS. It renders empty, which is degraded but
    //   can be deliberate — `$ARGUMENTS` as an optional addendum to a prompt
    //   that stands on its own is a legitimate template, and refusing would make
    //   such a workflow unrunnable without a dummy task.
    const consumesTask = consumed.has(TASK_INPUT_NAME);
    if (consumesTask && !supplied.has(TASK_INPUT_NAME) && !declaredDefault(declarations, TASK_INPUT_NAME)) {
      print(
        style("Warning:", YELLOW) +
          ` a phase prompt in '${wf.name}' consumes the task, but none was supplied — it will render empty.` +
          ` Pass -t "<task>".`,
      );
    }
    if (task !== undefined && !consumesTask) {
      printError(
        `no phase prompt in '${wf.name}' consumes the task — -t would be discarded and the workflow` +
          ` would run its own prompt instead.`,
      );
      printDim('Add $ARGUMENTS (or {{task}}) to a phase prompt, or drop -t to run the workflow as written.');
      throw new CLIError("Task not consumed by workflow", 1);
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

    // `printStarted` names the deployment as well as the execution: the same
    // workflow ID resolves to different definitions on different hosts, so an
    // execution ID on its own does not say which one ran (issue #1264).
    if (result.status === "started" && result.execution_id?.startsWith("exec-")) {
      printStarted(api, "\nWorkflow execution started", [
        { label: "Execution ID", value: result.execution_id },
        { label: "Workflow", value: wf.id },
      ]);
    } else {
      printError(`\nUnexpected server response from ${api.deployment}: status=${result.status} execution_id=${result.execution_id ?? "<none>"}`);
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
