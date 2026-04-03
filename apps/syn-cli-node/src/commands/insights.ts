/**
 * Insights commands — overview, cost, heatmap.
 * Port of apps/syn-cli/src/syn_cli/commands/insights.py
 */

import { CommandGroup, type CommandDef, type ParsedArgs } from "../framework/command.js";
import { apiGet } from "../client/api.js";
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
    const d = await apiGet<Record<string, unknown>>("/insights/overview");

    print(style("System Overview", CYAN));
    print(`  ${style("Total systems:", BOLD)}     ${d["total_systems"] ?? 0}`);
    print(`  ${style("Total repos:", BOLD)}       ${d["total_repos"] ?? 0}`);
    print(`  ${style("Active sessions:", BOLD)}   ${d["active_sessions"] ?? 0}`);
    print(`  ${style("Total executions:", BOLD)}  ${d["total_executions"] ?? 0}`);

    const health = d["health"] as Record<string, unknown> | undefined;
    if (health) {
      const h = String(health["status"] ?? "unknown");
      const color = h === "healthy" ? GREEN : h === "degraded" ? YELLOW : RED;
      print(`  ${style("Health:", BOLD)}           ${style(h, color)}`);
    }

    const systems = (d["systems"] ?? []) as Record<string, unknown>[];
    if (systems.length > 0) {
      const table = new Table({ title: "Systems" });
      table.addColumn("Name", { style: CYAN });
      table.addColumn("Repos", { align: "right" });
      table.addColumn("Health");
      table.addColumn("Executions", { align: "right" });

      for (const sys of systems) {
        const sh = String(sys["health"] ?? "unknown");
        const sc = sh === "healthy" ? GREEN : sh === "degraded" ? YELLOW : RED;
        table.addRow(
          String(sys["name"] ?? ""),
          String(sys["repo_count"] ?? 0),
          style(sh, sc),
          String(sys["execution_count"] ?? 0),
        );
      }
      table.print();
    }
  },
};

const costCommand: CommandDef = {
  name: "cost",
  description: "Show global cost breakdown",
  options: {
    days: { type: "string", short: "d", description: "Number of days to look back", default: "30" },
  },
  handler: async (parsed: ParsedArgs) => {
    const days = (parsed.values["days"] as string | undefined) ?? "30";
    const d = await apiGet<Record<string, unknown>>("/insights/cost", { params: { days } });

    print(style(`Cost Overview (last ${days} days)`, CYAN));
    print(`  ${style("Total cost:", BOLD)}   ${formatCost(String(d["total_cost_usd"] ?? "0"))}`);
    print(`  ${style("Total tokens:", BOLD)} ${formatTokens(Number(d["total_tokens"] ?? 0))}`);

    const byRepo = (d["by_repo"] ?? []) as Record<string, unknown>[];
    if (byRepo.length > 0) {
      const table = new Table({ title: "Cost by Repository" });
      table.addColumn("Repository", { style: CYAN });
      table.addColumn("Cost", { align: "right" });
      table.addColumn("Tokens", { align: "right" });
      for (const r of byRepo) {
        table.addRow(
          String(r["repo_name"] ?? r["repo_id"] ?? ""),
          formatCost(String(r["cost_usd"] ?? "0")),
          formatTokens(Number(r["tokens"] ?? 0)),
        );
      }
      table.print();
    }

    const byModel = (d["by_model"] ?? []) as Record<string, unknown>[];
    if (byModel.length > 0) {
      const table = new Table({ title: "Cost by Model" });
      table.addColumn("Model", { style: CYAN });
      table.addColumn("Cost", { align: "right" });
      for (const m of byModel) {
        table.addRow(
          String(m["model"] ?? ""),
          formatCost(String(m["cost_usd"] ?? "0")),
        );
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
    const days = (parsed.values["days"] as string | undefined) ?? "14";
    const d = await apiGet<Record<string, unknown>>("/insights/contribution-heatmap", { params: { days } });

    const buckets = (d["buckets"] ?? []) as Record<string, unknown>[];
    if (buckets.length === 0) { printDim("No activity data."); return; }

    const values = buckets.map((b) => Number(b["count"] ?? 0));
    print(style(`Activity Heatmap (last ${days} days)`, CYAN));
    print(`  ${renderSparkline(values)}`);
    print(style(`  ${values.reduce((a, b) => a + b, 0)} total events`, DIM));

    const topRepos = (d["top_repos"] ?? []) as Record<string, unknown>[];
    if (topRepos.length > 0) {
      const table = new Table({ title: "Top Repositories" });
      table.addColumn("Repository", { style: CYAN });
      table.addColumn("Events", { align: "right" });
      for (const r of topRepos.slice(0, 5)) {
        table.addRow(
          String(r["repo_name"] ?? r["repo_id"] ?? ""),
          String(r["count"] ?? 0),
        );
      }
      table.print();
    }
  },
};

export const insightsGroup = new CommandGroup("insights", "Global system insights and cost analysis");
insightsGroup.command(overviewCommand).command(costCommand).command(heatmapCommand);
