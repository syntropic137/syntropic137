/**
 * Execution list and detail commands.
 * Port of apps/syn-cli/src/syn_cli/commands/execution.py
 */

import { CommandGroup, type CommandDef, type ParsedArgs } from "../framework/command.js";
import { CLIError } from "../framework/errors.js";
import { api, unwrap } from "../client/typed.js";
import type { components } from "../generated/api-types.js";
import { print, printError, printDim } from "../output/console.js";
import { style, BOLD, CYAN, DIM, RED } from "../output/ansi.js";
import { formatCost, formatStatus, formatTimestamp, formatTokens } from "../output/format.js";
import { Table } from "../output/table.js";

type ExecutionList = components["schemas"]["ExecutionListResponse"];
type ExecutionDetail = components["schemas"]["ExecutionDetailResponse"];

const listCommand: CommandDef = {
  name: "list",
  description: "List all workflow executions",
  options: {
    status: { type: "string", short: "s", description: "Filter by status" },
    page: { type: "string", description: "Page number", default: "1" },
    "page-size": { type: "string", description: "Items per page (max 100)", default: "50" },
  },
  handler: async (parsed: ParsedArgs) => {
    const status = parsed.values["status"] as string | undefined;
    const pageStr = (parsed.values["page"] as string | undefined) ?? "1";
    const pageSizeStr = (parsed.values["page-size"] as string | undefined) ?? "50";

    const data: ExecutionList = unwrap(await api.GET("/executions", {
      params: {
        query: {
          status: status ?? null,
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
        formatCost(ex.total_cost_usd),
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
    print(`  Workflow:   ${ex.workflow_name}`);
    print(`  Status:     ${formatStatus(ex.status)}`);
    print(`  Started:    ${formatTimestamp(ex.started_at)}`);
    if (ex.completed_at) print(`  Completed:  ${formatTimestamp(ex.completed_at)}`);
    print(`  Tokens:     ${formatTokens(ex.total_tokens)}`);
    print(`  Cost:       ${formatCost(ex.total_cost_usd)}`);
    if (ex.error_message) print(`  ${style("Error:", RED)}     ${ex.error_message}`);

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
      table.addColumn("Started");
      table.addColumn("Tokens", { align: "right" });
      table.addColumn("Cost", { align: "right" });

      for (let i = 0; i < phases.length; i++) {
        const ph = phases[i]!;
        table.addRow(
          String(i + 1),
          ph.name,
          formatStatus(ph.status),
          formatTimestamp(ph.started_at),
          formatTokens(ph.total_tokens),
          formatCost(ph.cost_usd),
        );
      }
      table.print();
    }
  },
};

export const executionGroup = new CommandGroup("execution", "List and inspect workflow executions");
executionGroup.command(listCommand).command(showCommand);
