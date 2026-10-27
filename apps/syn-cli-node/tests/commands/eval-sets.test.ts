import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { evalGroup } from "../../src/commands/eval.js";
import { CLIError } from "../../src/framework/errors.js";
import type { components } from "../../src/generated/api-types.js";

type EvalSetMetrics = components["schemas"]["EvalSetMetricsResponse"];
type EvalSetCohort = components["schemas"]["EvalSetCohortResponse"];

describe("syn eval set (#2108)", () => {
  const mockFetch = vi.fn();
  const run = evalGroup.getCommand("set")!.handler;

  beforeEach(() => {
    vi.stubGlobal("fetch", mockFetch);
    vi.spyOn(process.stdout, "write").mockReturnValue(true);
    vi.spyOn(process.stderr, "write").mockReturnValue(true);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.resetAllMocks();
    vi.unstubAllGlobals();
  });

  function jsonResponse(data: unknown): Response {
    return new Response(JSON.stringify(data), { status: 200, headers: { "Content-Type": "application/json" } });
  }

  function stdout(): string {
    return (process.stdout.write as ReturnType<typeof vi.fn>).mock.calls.map((c: unknown[]) => String(c[0])).join("");
  }

  const bounds = (lower: number, upper: number, display: string) => ({ lower, upper, display });
  const key = (scorer: string) => ({
    suite_version: "8",
    workflow_id: "verify-v7",
    workflow_version: "v7",
    models_digest: "m".repeat(64),
    scorer_protocol: scorer,
  });

  function cohort(scorer: string): EvalSetCohort {
    return {
      cohort: key(scorer),
      k: 3,
      cases: [
        {
          eval_id: "eval-a", k: 3, n: 3, c: 2, pending: 0, infra_error_count: 1,
          base_mismatch_count: 0, treatment_mismatch_count: 0, trials_short: 0, exhausted: false,
          complete: true, never_launched: false,
          pass_at_k: 1, pass_at_k_display: "100%", pass_hat_k: 0, pass_hat_k_display: "0%", flaky: true,
          pass_at_k_bounds: bounds(1, 1, "100% to 100%"), pass_hat_k_bounds: bounds(0, 0.25, "0% to 25%"),
        },
      ],
      coverage: { roster_size: 2, complete: 1, short: 0, never_launched: 1 },
      mean_pass_at_k: 1, mean_pass_at_k_display: "100%",
      mean_pass_hat_k: 0, mean_pass_hat_k_display: "0%",
      flakiness: 1, partial: true, flaky_cases: ["eval-a"],
      pass_at_k_bounds: bounds(0.5, 1, "50% to 100%"), pass_hat_k_bounds: bounds(0, 0.625, "0% to 62%"),
      infra_error_count: 1, infra_share: 0.25, base_mismatch_count: 0, treatment_mismatch_count: 0,
      image_manifests: [], trials_without_image_manifest: 4,
    };
  }

  const body: EvalSetMetrics = {
    suite: "verifier-seed-v1",
    version: "8",
    split: "holdout",
    k: 3,
    roster: [
      { eval_id: "eval-a", split: "holdout", polarity: "defect" },
      { eval_id: "eval-b", split: "holdout", polarity: "clean" },
    ],
    cohorts: [cohort("keyword-v1"), cohort("panel-v1")],
    comparison: {
      a: key("keyword-v1"), b: key("panel-v1"), k: 3,
      paired_cases: [], short_cases: ["eval-a", "eval-b"], coverage_complete: false,
      a_only: 0, b_only: 0, both: 0, neither: 0, mcnemar_p: 1,
      difference: null, a_lower_minus_b_upper: null, a_upper_minus_b_lower: null,
    },
    not_a_trial_count: 2,
    isolation: "unproven",
  };

  it("sends suite, version, k and split, and prints the server's figures", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(body));

    await run({
      positionals: [],
      values: { suite: "verifier-seed-v1", "suite-version": "8", k: "3", split: "holdout" },
    });

    const request = mockFetch.mock.calls[0]![0] as Request;
    const url = new URL(request.url);
    expect(url.pathname).toMatch(/\/eval-sets\/metrics$/);
    expect(Object.fromEntries(url.searchParams)).toEqual({
      suite: "verifier-seed-v1", version: "8", k: "3", split: "holdout",
    });
    const out = stdout();
    expect(out).toContain("Eval set verifier-seed-v1 v8 split holdout, k=3");
    expect(out).toContain("1/2 complete, 0 short, 1 never launched");
    expect(out).toContain("0% to 62%");
    expect(out).toContain("(partial: descriptive only)");
    expect(out).toContain("incomplete: inconclusive");
    expect(out).toContain("isolation:       unproven");
  });

  it("refuses a missing --k without calling the API", async () => {
    await expect(
      run({ positionals: [], values: { suite: "s", "suite-version": "8" } }),
    ).rejects.toThrow(CLIError);
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("refuses a k below 1 without calling the API", async () => {
    await expect(
      run({ positionals: [], values: { suite: "s", "suite-version": "8", k: "0" } }),
    ).rejects.toThrow(CLIError);
    expect(mockFetch).not.toHaveBeenCalled();
  });
});
