/**
 * Insights commands — overview, cost, heatmap.
 * Port of apps/syn-cli/src/syn_cli/commands/insights.py
 */

import { CommandGroup, type CommandDef, type ParsedArgs } from "../framework/command.js";
import { api, unwrap } from "../client/typed.js";
import { print, printDim } from "../output/console.js";
import { style, BOLD, CYAN, DIM, GREEN, RED, YELLOW } from "../output/ansi.js";
import { formatCost, formatTokens } from "../output/format.js";
import { Table } from "../output/table.js";

const SPARKLINE_CHARS = " ▁▂▃▄▅▆▇█";

function renderSparkline(values: number[]): string {
  if (values.length === 0) return "";
  const max = Math.max(...values);
  if (max === 0) return SPARKLINE_CHARS[0]!.repeat(values.length);
  return values
    .map((v) => {
      const idx = Math.min(Math.round((v / max) * 8), 8);
      return SPARKLINE_CHARS[idx] ?? " ";
    })
    .join("");
}

const overviewCommand: CommandDef = {
  name: "overview",
  description: "Show global overview of systems and health",
  handler: async () => {
    const d = unwrap(await api.GET("/insights/overview"), "Fetch overview");

    print(style("System Overview", CYAN));
    print(`  ${style("Total systems:", BOLD)}     ${d.total_systems}`);
    print(`  ${style("Total repos:", BOLD)}       ${d.total_repos}`);
    print(`  ${style("Unassigned repos:", BOLD)}  ${d.unassigned_repos}`);
    print(`  ${style("Active executions:", BOLD)} ${d.total_active_executions}`);

    const systems = d.systems ?? [];
    if (systems.length > 0) {
      const table = new Table({ title: "Systems" });
      table.addColumn("Name", { style: CYAN });
      table.addColumn("Repos", { align: "right" });
      table.addColumn("Status");
      table.addColumn("Executions", { align: "right" });

      for (const sys of systems) {
        const sh = sys.overall_status;
        const sc = sh === "healthy" ? GREEN : sh === "degraded" ? YELLOW : RED;
        table.addRow(
          sys.system_name,
          String(sys.repo_count),
          style(sh, sc),
          String(sys.active_executions),
        );
      }
      table.print();
    }
  },
};

const costCommand: CommandDef = {
  name: "cost",
  description: "Show global cost breakdown",
  handler: async () => {
    const d = unwrap(await api.GET("/insights/cost"), "Fetch cost");

    print(style("Cost Overview", CYAN));
    print(`  ${style("Total cost:", BOLD)}   ${formatCost(d.total_cost_usd)}`);
    print(`  ${style("Total tokens:", BOLD)} ${formatTokens(d.total_tokens)}`);

    const byRepo = d.cost_by_repo ?? {};
    const repoEntries = Object.entries(byRepo);
    if (repoEntries.length > 0) {
      const table = new Table({ title: "Cost by Repository" });
      table.addColumn("Repository", { style: CYAN });
      table.addColumn("Cost", { align: "right" });
      for (const [repo, cost] of repoEntries) {
        table.addRow(repo, formatCost(cost));
      }
      table.print();
    }

    const byModel = d.cost_by_model ?? {};
    const modelEntries = Object.entries(byModel);
    if (modelEntries.length > 0) {
      const table = new Table({ title: "Cost by Model" });
      table.addColumn("Model", { style: CYAN });
      table.addColumn("Cost", { align: "right" });
      for (const [model, cost] of modelEntries) {
        table.addRow(model, formatCost(cost));
      }
      table.print();
    }
  },
};

const heatmapCommand: CommandDef = {
  name: "heatmap",
  description: "Show activity heatmap over time",
  options: {
    days: { type: "string", short: "d", description: "Number of days to show", default: "14" },
  },
  handler: async (parsed: ParsedArgs) => {
    const numDays = parseInt((parsed.values["days"] as string | undefined) ?? "14", 10);
    const endDate = new Date();
    const startDate = new Date();
    startDate.setDate(endDate.getDate() - numDays);
    const fmt = (dt: Date) => dt.toISOString().split("T")[0]!;

    const d = unwrap(await api.GET("/insights/contribution-heatmap", {
      params: { query: { start_date: fmt(startDate), end_date: fmt(endDate) } },
    }), "Fetch heatmap");

    const days = d.days ?? [];
    if (days.length === 0) { printDim("No activity data."); return; }

    const values = days.map((b) => b.count);
    print(style(`Activity Heatmap (last ${numDays} days)`, CYAN));
    print(`  ${renderSparkline(values)}`);
    print(style(`  ${d.total} total events`, DIM));
  },
};

export const insightsGroup = new CommandGroup("insights", "Global system insights and cost analysis");
insightsGroup.command(overviewCommand).command(costCommand).command(heatmapCommand);
