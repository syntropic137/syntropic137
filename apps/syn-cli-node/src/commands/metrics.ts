/**
 * Metrics commands — aggregated workflow and session metrics.
 * Port of apps/syn-cli/src/syn_cli/commands/metrics.py
 */

import { CommandGroup, type CommandDef, type ParsedArgs } from "../framework/command.js";
import { api, unwrap } from "../client/typed.js";
import { print, printDim } from "../output/console.js";
import { style, BOLD, CYAN } from "../output/ansi.js";
import { formatCost, formatDuration, formatStatus, formatTokens } from "../output/format.js";
import { Table } from "../output/table.js";

const showCommand: CommandDef = {
  name: "show",
  description: "Show aggregated workflow and session metrics",
  options: {
    workflow: { type: "string", short: "w", description: "Filter by workflow ID" },
  },
  handler: async (parsed: ParsedArgs) => {
    const workflow = (parsed.values["workflow"] as string | undefined) ?? null;

    const d = unwrap(await api.GET("/metrics", {
      params: { query: { workflow_id: workflow } },
    }), "Fetch metrics");

    print(style("Aggregated Metrics", CYAN));
    print(`  ${style("Workflows:", BOLD)}     ${d.total_workflows}`);
    print(`  ${style("Sessions:", BOLD)}      ${d.total_sessions}`);
    print(`  ${style("Input tokens:", BOLD)}  ${formatTokens(d.total_input_tokens)}`);
    print(`  ${style("Output tokens:", BOLD)} ${formatTokens(d.total_output_tokens)}`);
    print(`  ${style("Total cost:", BOLD)}    ${formatCost(d.total_cost_usd)}`);
    print(`  ${style("Artifacts:", BOLD)}     ${d.total_artifacts}`);

    const phases = d.phases ?? [];
    if (phases.length > 0) {
      const table = new Table({ title: "Phase Metrics" });
      table.addColumn("Phase");
      table.addColumn("Status");
      table.addColumn("Tokens", { align: "right" });
      table.addColumn("Cost", { align: "right" });
      table.addColumn("Duration", { align: "right" });
      table.addColumn("Artifacts", { align: "right" });

      for (const ph of phases) {
        table.addRow(
          ph.phase_name,
          formatStatus(ph.status),
          formatTokens(ph.total_tokens),
          formatCost(ph.cost_usd),
          formatDuration(ph.duration_seconds * 1000),
          String(ph.artifact_count),
        );
      }
      table.print();
    }

    if (phases.length === 0 && !d.total_workflows) {
      printDim("No metrics data available.");
    }
  },
};

export const metricsGroup = new CommandGroup("metrics", "View aggregated workflow and session metrics");
metricsGroup.command(showCommand);
