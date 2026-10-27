/**
 * `syn eval set --suite <s> --suite-version <n> --k <k> [--split <s>]` (#2108).
 *
 * Prints what `GET /eval-sets/metrics` computed: every cohort over the
 * roster, its coverage, its conditional means and the roster-wide bounds
 * decisions read, and the paired comparison when two cohorts launched. No
 * figure is computed here.
 */

import type { CommandDef, ParsedArgs } from "../framework/command.js";
import { CLIError } from "../framework/errors.js";
import { api, unwrap } from "../client/typed.js";
import type { components } from "../generated/api-types.js";
import { print, printDim, printError } from "../output/console.js";
import { style, CYAN, GREEN } from "../output/ansi.js";
import { Table } from "../output/table.js";

type EvalSetMetrics = components["schemas"]["EvalSetMetricsResponse"];
type EvalSetCohort = components["schemas"]["EvalSetCohortResponse"];
type EvalCohortKey = components["schemas"]["EvalCohortKeyResponse"];
type EvalSetComparison = components["schemas"]["EvalSetComparisonResponse"];
type EvalInterval = components["schemas"]["EvalIntervalResponse"];

function required(parsed: ParsedArgs, name: string): string {
  const value = parsed.values[name];
  if (typeof value !== "string" || value === "") {
    printError(`--${name} is required`);
    printDim("Usage: syn eval set --suite <suite> --suite-version <n> --k <k> [--split holdout]");
    throw new CLIError("Missing argument", 1);
  }
  return value;
}

function cohortLabel(key: EvalCohortKey): string {
  const version = key.workflow_version || "unrecorded";
  return `${key.workflow_id}@${version} models:${key.models_digest.slice(0, 12)} scorer:${key.scorer_protocol}`;
}

function printCohort(cohort: EvalSetCohort): void {
  const coverage = cohort.coverage;
  print(style(`Cohort ${cohortLabel(cohort.cohort)}`, GREEN));
  print(
    `  coverage:        ${coverage.complete}/${coverage.roster_size} complete, ` +
      `${coverage.short} short, ${coverage.never_launched} never launched`,
  );
  const partial = cohort.partial ? " (partial: descriptive only)" : "";
  print(`  pass@${cohort.k}:          ${cohort.mean_pass_at_k_display}${partial}`);
  print(`  pass^${cohort.k}:          ${cohort.mean_pass_hat_k_display}${partial}`);
  print(`  pass@${cohort.k} bounds:   ${cohort.pass_at_k_bounds.display}`);
  print(`  pass^${cohort.k} bounds:   ${cohort.pass_hat_k_bounds.display}`);
  print(`  flaky cases:     ${cohort.flaky_cases.join(", ") || "(none)"}`);
  print(
    `  infra errors:    ${cohort.infra_error_count}; excluded: ` +
      `${cohort.base_mismatch_count} base mismatch, ${cohort.treatment_mismatch_count} treatment mismatch`,
  );
  const images = cohort.image_manifests.map((m) => `${m.provider}@${m.build_commit.slice(0, 12)}`);
  print(
    `  images:          ${images.join(", ") || "(none read)"}; ` +
      `${cohort.trials_without_image_manifest} trial(s) without one`,
  );

  const table = new Table();
  table.addColumn("Eval", { style: CYAN });
  table.addColumn("n", { align: "right" });
  table.addColumn("c", { align: "right" });
  table.addColumn("Pending", { align: "right" });
  table.addColumn("Infra", { align: "right" });
  table.addColumn("Short", { align: "right" });
  table.addColumn(`pass@${cohort.k}`, { align: "right" });
  table.addColumn(`pass^${cohort.k}`, { align: "right" });
  table.addColumn(`pass^${cohort.k} bounds`);
  table.addColumn("Flaky");
  for (const c of cohort.cases) {
    table.addRow(
      c.eval_id,
      String(c.n),
      String(c.c),
      String(c.pending),
      String(c.infra_error_count),
      c.exhausted ? "exhausted" : String(c.trials_short),
      c.pass_at_k_display,
      c.pass_hat_k_display,
      c.pass_hat_k_bounds.display,
      c.flaky === null ? "-" : c.flaky ? "yes" : "no",
    );
  }
  table.print();
}

function interval(i: EvalInterval | null): string {
  return i === null ? "-" : `${i.estimate.toFixed(3)} [${i.low.toFixed(3)}, ${i.high.toFixed(3)}]`;
}

function printComparison(pair: EvalSetComparison): void {
  print(style(`Paired comparison (pass^${pair.k}, first k judged trials)`, GREEN));
  print(`  A: ${cohortLabel(pair.a)}`);
  print(`  B: ${cohortLabel(pair.b)}`);
  print(`  paired cases:    ${pair.paired_cases.length}; short: ${pair.short_cases.join(", ") || "(none)"}`);
  print(`  coverage:        ${pair.coverage_complete ? "complete" : "incomplete: inconclusive"}`);
  print(`  A only / B only: ${pair.a_only} / ${pair.b_only} (both ${pair.both}, neither ${pair.neither})`);
  print(`  McNemar p:       ${pair.mcnemar_p}`);
  print(`  A - B:           ${interval(pair.difference)}`);
  print(`  A_low - B_high:  ${interval(pair.a_lower_minus_b_upper)}`);
  print(`  A_high - B_low:  ${interval(pair.a_upper_minus_b_lower)}`);
}

export const evalSetCommand: CommandDef = {
  name: "set",
  description: "pass@k, pass^k and flakiness of every cohort over an eval set's roster",
  options: {
    suite: { type: "string", description: "The eval set: evals tagged suite:<suite>" },
    "suite-version": { type: "string", description: "The roster version: suite-version:<n>" },
    k: { type: "string", description: "Trials per case the figures are computed over" },
    split: { type: "string", description: "Keep only cases of this split, e.g. holdout" },
    json: { type: "boolean", description: "Print the API response as JSON", default: false },
  },
  examples: ["syn eval set --suite verifier-seed-v1 --suite-version 8 --k 3 --split holdout"],
  handler: async (parsed: ParsedArgs) => {
    const suite = required(parsed, "suite");
    const version = required(parsed, "suite-version");
    const k = parseInt(required(parsed, "k"), 10);
    if (!Number.isInteger(k) || k < 1) throw new CLIError("--k must be a positive integer", 1);
    const split = parsed.values["split"] as string | undefined;
    const data = unwrap<EvalSetMetrics>(
      await api.GET("/eval-sets/metrics", {
        params: { query: { suite, version, k, ...(split ? { split } : {}) } },
      }),
      "Eval set metrics",
    );
    if (parsed.values["json"] === true) {
      print(JSON.stringify(data, null, 2));
      return;
    }
    const scope = data.split ? ` split ${data.split}` : "";
    print(style(`Eval set ${data.suite} v${data.version}${scope}, k=${data.k}`, GREEN));
    print(`  roster:          ${data.roster.length} case(s); ${data.not_a_trial_count} member run(s) in no cohort`);
    print(`  isolation:       ${data.isolation}`);
    if (data.cohorts.length === 0) {
      printDim("No cohort has launched into this roster.");
      return;
    }
    for (const cohort of data.cohorts) printCohort(cohort);
    if (data.comparison) printComparison(data.comparison);
    printDim("Decide on the bounds, not the partial means; bounds that straddle the line need a top-up.");
  },
};
