/**
 * Metrics commands — aggregated workflow and session metrics.
 * Port of apps/syn-cli/src/syn_cli/commands/metrics.py
 */

import { CommandGroup, type CommandDef, type ParsedArgs } from "../framework/command.js";
import { api, unwrap } from "../client/typed.js";
import { print, printDim, printError } from "../output/console.js";
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
          ph.duration_seconds != null
            ? formatDuration(ph.duration_seconds * 1000)
            : "\u2014",
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

const profilesCommand: CommandDef = {
  name: "profiles",
  description: "Per-phase p50/p90 token and cost, p50/p95 resource profiles for a workflow",
  options: {
    workflow: { type: "string", short: "w", description: "Workflow ID (required)" },
    days: { type: "string", short: "d", description: "Look-back window in days", default: "7" },
  },
  handler: async (parsed: ParsedArgs) => {
    const workflow = parsed.values["workflow"] as string | undefined;
    if (!workflow) {
      printError("--workflow is required");
      process.exitCode = 1;
      return;
    }
    const days = Number((parsed.values["days"] as string | undefined) ?? "7");

    const d = unwrap(await api.GET("/metrics/phase-profiles", {
      params: { query: { workflow_id: workflow, window_days: days } },
    }), "Fetch phase profiles");

    print(style(`Phase profiles: ${d.workflow_id} (last ${d.window_days}d, ${d.executions} executions)`, CYAN));

    const tokens = new Table({ title: "Tokens and cost per phase and model (p50 / p90)" });
    for (const col of ["Phase", "Model", "n", "Input", "Output", "Cache write", "Cache read", "Cost"]) {
      tokens.addColumn(col, col === "Phase" || col === "Model" ? {} : { align: "right" });
    }
    for (const t of d.tokens) {
      const pair = (p: { p50_display: string; p90_display: string }) =>
        p.p50_display === p.p90_display ? p.p50_display : `${p.p50_display} / ${p.p90_display}`;
      tokens.addRow(
        t.phase_id,
        t.model,
        String(t.input_tokens.n),
        pair(t.input_tokens),
        pair(t.output_tokens),
        pair(t.cache_creation_tokens),
        pair(t.cache_read_tokens),
        pair(t.cost_usd) + (t.unpriced_phases ? ` (${t.unpriced_phases} unpriced)` : ""),
      );
    }
    if (d.tokens.length > 0) tokens.print();
    else printDim("No token usage recorded for this workflow in the window.");

    const resources = new Table({ title: "Workspace resources per phase (p50 / p95)" });
    for (const col of ["Phase", "Coverage", "CPU s / wall s", "Throttled", "Memory peak", "Disk at teardown"]) {
      resources.addColumn(col, col === "Phase" || col === "Coverage" ? {} : { align: "right" });
    }
    for (const r of d.resources) {
      const pair = (p: { p50_display: string; p95_display: string }) =>
        p.p50_display === p.p95_display ? p.p50_display : `${p.p50_display} / ${p.p95_display}`;
      resources.addRow(
        r.phase_id,
        r.coverage.coverage_display,
        pair(r.cpu_seconds_per_wall_second),
        pair(r.cpu_throttled_seconds),
        pair(r.memory_peak_bytes),
        pair(r.disk_bytes_at_teardown),
      );
    }
    if (d.resources.length > 0) resources.print();

    // Which phases each resource percentile stands on. Scope: every phase of
    // this type with telemetry in the window. "missing" counts usage rows that
    // exist but lack the field; a CPU rate also needs the workspace lifetime.
    const coverage = new Table({ title: "Resource coverage per phase (n used / missing in a usage row)" });
    for (const col of ["Phase", "Phases", "No usage row", "CPU s / wall s", "Lifetime missing", "Throttled", "Memory peak", "Disk at teardown"]) {
      coverage.addColumn(col, col === "Phase" ? {} : { align: "right" });
    }
    for (const r of d.resources) {
      const c = r.coverage;
      const used = (n: number, missing: number) => `${n} / ${missing}`;
      coverage.addRow(
        r.phase_id,
        String(c.phases),
        String(c.phases_without_usage_row),
        used(r.cpu_seconds_per_wall_second.n, c.cpu_usage_seconds_missing),
        String(c.wall_seconds_missing),
        used(r.cpu_throttled_seconds.n, c.cpu_throttled_seconds_missing),
        used(r.memory_peak_bytes.n, c.memory_peak_bytes_missing),
        used(r.disk_bytes_at_teardown.n, c.disk_bytes_at_teardown_missing),
      );
    }
    if (d.resources.length > 0) coverage.print();
    printDim("Percentiles over every phase in the window; fewer than 10 phases reads 'insufficient'.");
  },
};

const shippedCommand: CommandDef = {
  name: "shipped",
  description: "What agents shipped: commits, PRs, merge rate, repos touched vs the previous window",
  options: {
    days: { type: "string", short: "d", description: "Window in UTC days: 7, 14 or 30", default: "14" },
    workflow: { type: "string", short: "w", description: "Only this workflow's executions" },
    json: { type: "boolean", description: "Print the API response as JSON", default: false },
  },
  examples: ["syn metrics shipped --days 14 --json", "syn metrics shipped -w sdlc-implement"],
  handler: async (parsed: ParsedArgs) => {
    const days = Number((parsed.values["days"] as string | undefined) ?? "14");
    if (days !== 7 && days !== 14 && days !== 30) {
      printError("--days must be 7, 14 or 30");
      process.exitCode = 1;
      return;
    }
    const workflow = (parsed.values["workflow"] as string | undefined) ?? null;

    const d = unwrap(await api.GET("/metrics/shipped", {
      params: { query: { days, workflow_id: workflow } },
    }), "Fetch shipped metrics");

    if (parsed.values["json"] === true) {
      print(JSON.stringify(d, null, 2));
      return;
    }

    const scope = d.workflow_id ? ` for ${d.workflow_id}` : "";
    print(style(`Shipped by agents${scope}, ${d.window.from} to ${d.window.to} (vs ${d.previous.from} to ${d.previous.to})`, CYAN));
    const table = new Table();
    table.addColumn("Tile");
    table.addColumn("Total", { align: "right" });
    table.addColumn("Delta", { align: "right" });
    table.addColumn("Note");
    const tiles = [
      ["Commits", d.commits],
      ["PRs opened", d.prs_opened],
      ["PRs merged", d.prs_merged],
      ["Merge rate", d.merge_rate],
      ["Repos touched", d.repos_touched],
    ] as const;
    for (const [label, tile] of tiles) {
      table.addRow(label, tile.total_display ?? "\u2014", tile.delta_display ?? "\u2014", tile.reason ? "unavailable" : "");
    }
    table.print();
    if (d.repos.length > 0) printDim(`Repos: ${d.repos.join(", ")}`);
    for (const [label, tile] of tiles) {
      if (tile.reason) printDim(`${label}: ${tile.reason}`);
    }
    if (d.by_workflow && d.by_workflow.length > 0) {
      const wf = new Table({ title: "By workflow (commits)" });
      wf.addColumn("Workflow");
      wf.addColumn("Commits", { align: "right" });
      wf.addColumn("Repos", { align: "right" });
      for (const b of d.by_workflow) wf.addRow(b.workflow_name || b.workflow_id, String(b.commits), String(b.repos_touched));
      wf.print();
    }
  },
};

export const metricsGroup = new CommandGroup("metrics", "View aggregated workflow and session metrics");
metricsGroup.command(showCommand);
metricsGroup.command(profilesCommand);
metricsGroup.command(shippedCommand);
