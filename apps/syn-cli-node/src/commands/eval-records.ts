/**
 * `syn eval create|list|show|runs|archive` (#967).
 *
 * `create` and `archive` print the server's receipt, read from the Eval
 * aggregate. `list` and `show` read the eval read model, which can trail a
 * create by a moment, so `create` says so rather than reading back.
 */

import type { CommandDef, ParsedArgs } from "../framework/command.js";
import { CLIError } from "../framework/errors.js";
import { api, unwrap } from "../client/typed.js";
import type { components } from "../generated/api-types.js";
import { print, printDim, printError } from "../output/console.js";
import { style, CYAN, GREEN } from "../output/ansi.js";
import { formatCostWithCoverage, formatStatus, formatTimestamp } from "../output/format.js";
import { Table } from "../output/table.js";

type EvalCreated = components["schemas"]["EvalCreatedResponse"];
type EvalArchived = components["schemas"]["EvalArchivedResponse"];
type Eval = components["schemas"]["EvalResponse"];
type EvalList = components["schemas"]["EvalListResponse"];
type EvalBaselineRepoRequest = components["schemas"]["EvalBaselineRepoRequest"];
type EvalBaselineRepo = components["schemas"]["EvalBaselineRepoResponse"];
type ExecutionList = components["schemas"]["ExecutionListResponse"];

const evalIdArg = [{ name: "eval-id", description: "The eval", required: true }] as const;

function strings(value: unknown): string[] {
  if (Array.isArray(value)) return value as string[];
  return typeof value === "string" ? [value] : [];
}

function requireEvalId(parsed: ParsedArgs, verb: string): string {
  const evalId = parsed.positionals[0];
  if (!evalId) {
    printError("eval-id is required");
    printDim(`Usage: syn eval ${verb} <eval-id>`);
    throw new CLIError("Missing argument", 1);
  }
  return evalId;
}

/** `owner/name@ref` -> the request's baseline repo. */
export function parseBaselineRepo(spec: string): EvalBaselineRepoRequest {
  const at = spec.indexOf("@");
  if (at <= 0 || at === spec.length - 1) {
    throw new CLIError(`--repo must be owner/name@ref, got "${spec}"`, 1);
  }
  return { repository: spec.slice(0, at), requested_ref: spec.slice(at + 1) };
}

function printBaseline(repos: EvalBaselineRepo[]): void {
  if (repos.length === 0) {
    print("  baseline_repos:       (none)");
    return;
  }
  print("  baseline_repos:");
  for (const repo of repos) print(`    ${repo.repository}@${repo.requested_ref} -> ${repo.commit_sha}`);
}

const createCommand: CommandDef = {
  name: "create",
  description: "Create an eval, pinning each --repo ref to a commit SHA",
  options: {
    name: { type: "string", description: "Eval name" },
    goal: { type: "string", description: "What the eval sets out to measure" },
    workflow: { type: "string", description: "Starting workflow id (used when a run names none)" },
    repo: { type: "string", description: "Baseline repo as owner/name@ref (repeatable)", multiple: true },
    tag: { type: "string", description: "Tag (repeatable)", multiple: true },
  },
  examples: [
    'syn eval create --name "Refactor" --goal "Does it keep tests green?" --repo acme/app@main',
  ],
  handler: async (parsed: ParsedArgs) => {
    const name = parsed.values["name"] as string | undefined;
    const goal = parsed.values["goal"] as string | undefined;
    if (!name || !goal) {
      printError("--name and --goal are required");
      throw new CLIError("Missing option", 1);
    }
    const data = unwrap<EvalCreated>(
      await api.POST("/evals", {
        body: {
          name,
          goal,
          starting_workflow_id: (parsed.values["workflow"] as string | undefined) ?? null,
          baseline_repos: strings(parsed.values["repo"]).map(parseBaselineRepo),
          tags: strings(parsed.values["tag"]),
        },
      }),
      "Create eval",
    );
    print(style(`Created eval ${data.eval_id}`, GREEN));
    print(`  name:                 ${data.name}`);
    print(`  goal:                 ${data.goal}`);
    print(`  starting_workflow_id: ${data.starting_workflow_id ?? "(none)"}`);
    printBaseline(data.baseline_repos);
    print(`  tags:                 ${data.tags.join(", ") || "(none)"}`);
    printDim("`syn eval list` and `syn eval show` may take a moment to show it.");
  },
};

const listCommand: CommandDef = {
  name: "list",
  description: "List evals, newest first, with their run counts",
  options: {
    status: { type: "string", short: "s", description: "active or archived (both when omitted)" },
    tag: { type: "string", description: "Only evals carrying this tag (repeatable; all must match)", multiple: true },
    page: { type: "string", description: "Page number", default: "1" },
    "page-size": { type: "string", description: "Items per page", default: "50" },
  },
  handler: async (parsed: ParsedArgs) => {
    const status = parsed.values["status"] as string | undefined;
    if (status !== undefined && status !== "active" && status !== "archived") {
      throw new CLIError(`--status must be active or archived, got "${status}"`, 1);
    }
    const tags = strings(parsed.values["tag"]);
    const page = parseInt((parsed.values["page"] as string | undefined) ?? "1", 10);
    const pageSize = parseInt((parsed.values["page-size"] as string | undefined) ?? "50", 10);
    const data = unwrap<EvalList>(
      await api.GET("/evals", {
        params: {
          query: {
            status: status ?? null,
            ...(tags.length > 0 ? { tag: tags } : {}),
            page,
            page_size: pageSize,
          },
        },
      }),
      "List evals",
    );
    if (data.evals.length === 0) { printDim("No evals found."); return; }

    const table = new Table({ title: `Evals (page ${page}, ${data.total} total)` });
    table.addColumn("ID", { style: CYAN });
    table.addColumn("Name");
    table.addColumn("Runs", { align: "right" });
    table.addColumn("Frozen");
    table.addColumn("Archived");
    table.addColumn("Created");
    for (const ev of data.evals) {
      table.addRow(
        ev.eval_id,
        ev.name,
        String(ev.run_count),
        ev.frozen ? "yes" : "no",
        ev.archived ? "yes" : "no",
        formatTimestamp(ev.created_at),
      );
    }
    table.print();
    if (data.total > page * pageSize) printDim(`Showing page ${page}. Use --page ${page + 1} for more.`);
  },
};

const showCommand: CommandDef = {
  name: "show",
  description: "Show an eval: goal, baseline and run tally",
  args: evalIdArg,
  handler: async (parsed: ParsedArgs) => {
    const evalId = requireEvalId(parsed, "show");
    const data = unwrap<Eval>(
      await api.GET("/evals/{eval_id}", { params: { path: { eval_id: evalId } } }),
      "Show eval",
    );
    print(style(`Eval ${data.eval_id}`, GREEN));
    print(`  name:                 ${data.name}`);
    print(`  goal:                 ${data.goal}`);
    print(`  starting_workflow_id: ${data.starting_workflow_id ?? "(none)"}`);
    printBaseline(data.baseline_repos);
    print(`  tags:                 ${data.tags.join(", ") || "(none)"}`);
    print(`  frozen:               ${data.frozen ? "yes" : "no"}`);
    print(`  archived:             ${data.archived ? "yes" : "no"}`);
    const tally = Object.entries(data.run_status_counts).map(([s, n]) => `${s}: ${n}`).join(", ");
    print(`  run_count:            ${data.run_count}${tally ? ` (${tally})` : ""}`);
    printDim(`Runs: syn eval runs ${data.eval_id}`);
  },
};

const runsCommand: CommandDef = {
  name: "runs",
  description: "List the executions currently in an eval",
  args: evalIdArg,
  options: {
    page: { type: "string", description: "Page number", default: "1" },
    "page-size": { type: "string", description: "Items per page", default: "50" },
  },
  handler: async (parsed: ParsedArgs) => {
    const evalId = requireEvalId(parsed, "runs");
    const page = parseInt((parsed.values["page"] as string | undefined) ?? "1", 10);
    const pageSize = parseInt((parsed.values["page-size"] as string | undefined) ?? "50", 10);
    const data = unwrap<ExecutionList>(
      await api.GET("/evals/{eval_id}/runs", {
        params: { path: { eval_id: evalId }, query: { page, page_size: pageSize } },
      }),
      "List eval runs",
    );
    if (data.executions.length === 0) { printDim("No runs in this eval."); return; }

    const table = new Table({ title: `Runs of ${evalId} (page ${page}, ${data.total} total)` });
    table.addColumn("ID", { style: CYAN });
    table.addColumn("Workflow");
    table.addColumn("Status");
    table.addColumn("Started");
    table.addColumn("Cost", { align: "right" });
    for (const ex of data.executions) {
      table.addRow(
        ex.workflow_execution_id,
        ex.workflow_name,
        formatStatus(ex.status),
        formatTimestamp(ex.started_at),
        formatCostWithCoverage(ex.total_cost_usd, ex.unpriced_observation_count),
      );
    }
    table.print();
    if (data.total > page * pageSize) printDim(`Showing page ${page}. Use --page ${page + 1} for more.`);
  },
};

const archiveCommand: CommandDef = {
  name: "archive",
  description: "Archive an eval: it stays readable with its runs and admits no new ones",
  args: evalIdArg,
  handler: async (parsed: ParsedArgs) => {
    const evalId = requireEvalId(parsed, "archive");
    const data = unwrap<EvalArchived>(
      await api.POST("/evals/{eval_id}/archive", { params: { path: { eval_id: evalId } } }),
      "Archive eval",
    );
    print(style(`Archived eval ${data.eval_id}`, GREEN));
  },
};

export const evalRecordCommands: CommandDef[] = [
  createCommand,
  listCommand,
  showCommand,
  runsCommand,
  archiveCommand,
];
