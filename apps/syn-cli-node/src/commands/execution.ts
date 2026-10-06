/**
 * Execution list and detail commands.
 * Port of apps/syn-cli/src/syn_cli/commands/execution.py
 */

import { CommandGroup, type CommandDef, type ParsedArgs } from "../framework/command.js";
import { CLIError } from "../framework/errors.js";
import { api, errorDetail, unwrap } from "../client/typed.js";
import type { components } from "../generated/api-types.js";
import { print, printError, printDim } from "../output/console.js";
import { style, BOLD, CYAN, DIM, GREEN, RED, YELLOW } from "../output/ansi.js";
import { formatCostWithCoverage, formatStatus, formatTimestamp, formatTokens } from "../output/format.js";
import { executionSessionsCommand } from "./execution-sessions.js";
import { executionTranscriptCommand } from "./execution-transcript.js";
import { executionTagCommand } from "./execution-tags.js";
import { Table } from "../output/table.js";

type ExecutionList = components["schemas"]["ExecutionListResponse"];
type ExecutionDetail = components["schemas"]["ExecutionDetailResponse"];
type InventorySummary = components["schemas"]["SessionInventorySummary"];
type ResumeStart = components["schemas"]["ResumeStartInfo"];
type StartQueue = components["schemas"]["ExecutionStartQueueInfo"];
type SideEffectStatus = components["schemas"]["SideEffectStatus"];
type FailureClassification = components["schemas"]["FailureClassification"];
type ReportedFailureReason = components["schemas"]["ReportedFailureReason"];

const listCommand: CommandDef = {
  name: "list",
  description: "List all workflow executions",
  options: {
    status: { type: "string", short: "s", description: "Filter by status" },
    tag: { type: "string", description: "Only executions carrying this tag (repeatable; all must match)", multiple: true },
    page: { type: "string", description: "Page number", default: "1" },
    "page-size": { type: "string", description: "Items per page (max 100)", default: "50" },
  },
  handler: async (parsed: ParsedArgs) => {
    const status = parsed.values["status"] as string | undefined;
    const tagValues = parsed.values["tag"];
    const tags: string[] = Array.isArray(tagValues) ? tagValues as string[] : tagValues ? [tagValues as string] : [];
    const pageStr = (parsed.values["page"] as string | undefined) ?? "1";
    const pageSizeStr = (parsed.values["page-size"] as string | undefined) ?? "50";

    const data: ExecutionList = unwrap(await api.GET("/executions", {
      params: {
        query: {
          status: status ?? null,
          ...(tags.length > 0 ? { tag: tags } : {}),
          page: parseInt(pageStr, 10),
          page_size: parseInt(pageSizeStr, 10),
        },
      },
    }), "Failed to list executions");

    const { executions, total } = data;
    const page = parseInt(pageStr, 10);
    const pageSize = parseInt(pageSizeStr, 10);

    if (executions.length === 0) { printDim("No executions found."); return; }

    const table = new Table({ title: `Executions (page ${page}, ${total} total)` });
    table.addColumn("ID", { style: CYAN });
    table.addColumn("Workflow");
    table.addColumn("Status");
    table.addColumn("Started");
    table.addColumn("Phases", { align: "right" });
    table.addColumn("Tokens", { align: "right" });
    table.addColumn("Cost", { align: "right" });
    table.addColumn("Repos");

    for (const ex of executions) {
      const repos = ex.repos ?? [];
      const reposCell = repos.length === 0
        ? ""
        : repos.length === 1
          ? (repos[0]!.split("/").pop()?.replace(/\.git$/, "") ?? repos[0]!)
          : `${repos.length} repos`;
      table.addRow(
        ex.workflow_execution_id,
        ex.workflow_name,
        formatStatus(ex.status),
        formatTimestamp(ex.started_at),
        `${ex.completed_phases}/${ex.total_phases}`,
        formatTokens(ex.total_tokens),
        formatCostWithCoverage(ex.total_cost_usd, ex.unpriced_observation_count),
        reposCell,
      );
    }
    table.print();
    if (total > page * pageSize) printDim(`Showing page ${page}. Use --page ${page + 1} for more.`);
  },
};

const showCommand: CommandDef = {
  name: "show",
  description: "Show detailed information about a single execution",
  args: [{ name: "execution-id", description: "Execution ID", required: true }],
  examples: [
    "syn execution show <execution-id>       # phases, cost and a session inventory summary",
    "syn execution sessions <execution-id> --all   # every session of the run (the summary's Details line)",
  ],
  handler: async (parsed: ParsedArgs) => {
    const id = parsed.positionals[0];
    if (!id) {
      printError("execution-id is required");
      printDim("Hint: run `syn execution list` to find an execution ID.");
      throw new CLIError("Missing argument", 1);
    }

    const ex: ExecutionDetail = unwrap(await api.GET("/executions/{execution_id}", {
      params: { path: { execution_id: id } },
    }), "Failed to get execution");

    print(`${style("Execution:", BOLD)} ${ex.workflow_execution_id}`);
    print(`  Workflow:     ${ex.workflow_name}`);
    print(`  Status:       ${formatStatus(ex.status)}`);
    // Accepted but waiting for a slot in the execution budget (#1557): there is
    // no execution record yet, so this is the only place its wait shows.
    if (ex.start_queue) print(`  Queue:        ${formatStartQueue(ex.start_queue)}`);
    if ((ex.tags ?? []).length > 0) print(`  Tags:         ${(ex.tags ?? []).join(", ")}`);
    print(`  Started:      ${formatTimestamp(ex.started_at)}`);
    if (ex.completed_at) print(`  Completed:    ${formatTimestamp(ex.completed_at)}`);
    print(`  Tokens:       ${formatTokens(ex.total_tokens)}`);
    print(`  Cost:         ${formatCostWithCoverage(ex.total_cost_usd, ex.unpriced_observation_count)}`);
    // The outcome, beside the status rather than implied by it: a run can fail
    // after its deliverable exists, or complete while its write-back was
    // refused (#1501).
    print(`  Deliverable:  ${ex.deliverable_produced ? "yes" : "no"}`);
    print(`  Side effects: ${formatSideEffects(ex.reported_side_effects)}`);
    if (ex.status === "failed") {
      print(`  ${style("Failure:", RED)}      ${formatFailure(ex.failure_classification, ex.reported_failure_reason)}`);
    }
    if (ex.error_message) print(`  ${style("Error:", RED)}        ${ex.error_message}`);
    if (ex.resume_start) printResumeStart(ex.resume_start);

    const repos = ex.repos ?? [];
    if (repos.length > 0) {
      print(`  Repos:`);
      for (const url of repos) {
        const name = url.split("/").pop()?.replace(/\.git$/, "") ?? url;
        print(`    ${style("•", CYAN)} ${name} ${style(`(${url})`, DIM)}`);
      }
    }

    const phases = ex.phases ?? [];
    if (phases.length > 0) {
      print("");
      const table = new Table({ title: "Phases" });
      table.addColumn("#", { align: "right", style: DIM });
      table.addColumn("Name");
      table.addColumn("Status");
      table.addColumn("Model");
      table.addColumn("Started");
      table.addColumn("Tokens", { align: "right" });
      table.addColumn("Cost", { align: "right" });
      table.addColumn("Side effects");

      for (let i = 0; i < phases.length; i++) {
        const ph = phases[i]!;
        table.addRow(
          String(i + 1),
          ph.name,
          // A salvaged phase completes, so its status alone would hide that
          // the deliverable came from the transcript, not the file (#1479).
          ph.deliverable_recovered
            ? `${formatStatus(ph.status)} ${style("(recovered)", YELLOW)}`
            : formatStatus(ph.status),
          // What RAN, or "unknown (requested: X)" - never the alias (ADR-067 D9).
          ph.model_display,
          formatTimestamp(ph.started_at),
          formatTokens(ph.total_tokens),
          formatCostWithCoverage(ph.cost_usd, ph.unpriced_observation_count),
          formatSideEffects(ph.reported_side_effects),
        );
      }
      table.print();

      // Below the table, not in it: an error is a sentence, and the phase a
      // reader opens first must say why it failed, not only that it did.
      for (const ph of phases.filter((p) => p.status === "failed")) {
        print(`  ${style("✗", RED)} ${ph.name}: ${formatFailure(ph.failure_classification, ph.reported_failure_reason)}`);
        print(`    ${ph.error_message || style("no error recorded", DIM)}`);
      }
    }
    await printInventorySummary(ex.workflow_execution_id);
  },
};

/** Why a run or phase failed: the classification, then what its agent SAID
 * caused it, kept apart because only the first is a measurement (#1392). */
function formatFailure(
  classification: FailureClassification | null | undefined,
  reported: ReportedFailureReason | null | undefined,
): string {
  const measured = classification ?? "unclassified";
  return reported ? `${measured} (agent reported: ${reported})` : measured;
}

/** What an agent SAID about its external writes. Null is its own answer, the
 * agent said nothing, and is never shown as "none", which is a claim. */
function formatSideEffects(status: SideEffectStatus | null | undefined): string {
  return status ?? "not reported";
}

/**
 * The start of the child this execution's resume admitted (#1480). A resume
 * returns 200 before its child starts, so a child that never appears is
 * explained here and nowhere else.
 */
function printResumeStart(resume: ResumeStart): void {
  print("");
  print(`${style("Resume start:", BOLD)} ${formatStatus(resume.status)}`);
  print(`  Attempts:   ${resume.attempts}/${resume.max_attempts}`);
  if (resume.status_reason) print(`  ${style("Reason:", RED)}    ${resume.status_reason}`);
  if (resume.start_queue) print(`  Queue:      ${formatStartQueue(resume.start_queue)}`);
}

/** Where a start stands in the execution budget, e.g. "queued 2 of 3 (4/4 running) via resume". */
function formatStartQueue(queue: StartQueue): string {
  return `${queue.position_display} via ${queue.path}`;
}

/**
 * Inventory is additive context: an execution whose inventory cannot be read
 * (not yet reconstructed, runtime disabled) still shows, with the reason.
 */
async function readInventorySummary(executionId: string): Promise<InventorySummary | string> {
  try {
    const result = await api.GET("/executions/{execution_id}/session-inventory", {
      params: { path: { execution_id: executionId } },
    });
    if (result.data?.summary && result.error === undefined && result.response.ok) return result.data.summary;
    const status = `unavailable (${result.response.status})`;
    return result.error === undefined ? status : `${status}: ${errorDetail(result.error)}`;
  } catch {
    return "unavailable";
  }
}

async function printInventorySummary(executionId: string): Promise<void> {
  const summary = await readInventorySummary(executionId);
  if (typeof summary === "string") {
    printDim(`\nSession inventory: ${summary}`);
    return;
  }
  print("");
  print(`${style("Session inventory:", BOLD)} ${summary.counts_display}`);
  print(`  Coverage:   ${summary.coverage_display}${summary.complete ? "" : " (incomplete)"}`);
  print(`  Details:    ${summary.follow_up_command}`);
}


type ResumeResponse = components["schemas"]["ResumeResponse"];

const resumeCommand: CommandDef = {
  name: "resume",
  description: "Resume a failed execution so it restarts at the first phase that did not finish",
  args: [{ name: "execution-id", description: "Execution to resume", required: true }],
  options: {
    "override-cancellation": {
      type: "boolean",
      description: "Resume a CANCELLED execution (a cancel is an instruction to stop)",
    },
    "acknowledge-external-effects": {
      type: "boolean",
      description: "Accept that re-running the resumed phase may repeat a push or publish",
    },
  },
  handler: async (parsed: ParsedArgs) => {
    const id = parsed.positionals[0];
    if (!id) {
      printError("execution-id is required");
      printDim("Hint: run `syn execution list --status failed` to find one.");
      throw new CLIError("Missing argument", 1);
    }
    const body = {
      override_cancellation: Boolean(parsed.values["override-cancellation"]),
      acknowledge_external_effects: Boolean(parsed.values["acknowledge-external-effects"]),
    };
    const data = unwrap<ResumeResponse>(
      await api.POST("/executions/{execution_id}/resume", {
        params: { path: { execution_id: id } },
        body,
      }),
      "Resume execution",
    );

    print(style(`Resumed ${data.parent_execution_id}`, GREEN));
    print(`  New execution: ${data.execution_id}`);
    print(`  Resumes at:    ${data.resume_phase_id}`);
    if (data.inherited_phase_ids.length > 0) {
      print(`  Not re-run:    ${data.inherited_phase_ids.join(", ")}`);
    } else {
      printDim("  Nothing inherited - the resume starts from the first phase.");
    }
    if (data.cancellation_overridden) {
      print(style("  Cancellation overridden", YELLOW));
    }
    if (data.external_effects_acknowledged) {
      print(style("  External effects acknowledged", YELLOW));
    }
    printDim(`Follow it with: syn execution show ${data.execution_id}`);
  },
};

export const executionGroup = new CommandGroup("execution", "List and inspect workflow executions, their sessions and transcripts");
executionGroup
  .command(listCommand)
  .command(showCommand)
  .command(resumeCommand)
  .command(executionTagCommand)
  .command(executionSessionsCommand)
  .command(executionTranscriptCommand);
