import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { evalGroup } from "../../src/commands/eval.js";
import { parseBaselineRepo } from "../../src/commands/eval-records.js";
import { CLIError } from "../../src/framework/errors.js";

describe("syn eval create|list|show|runs|archive (#967)", () => {
  const mockFetch = vi.fn();
  const run = (name: string) => evalGroup.getCommand(name)!.handler;

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

  function jsonResponse(data: unknown, status = 200): Response {
    return new Response(JSON.stringify(data), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  }

  function stdout(): string {
    return (process.stdout.write as ReturnType<typeof vi.fn>).mock.calls
      .map((c: unknown[]) => String(c[0]))
      .join("");
  }

  function sent(): Request {
    expect(mockFetch).toHaveBeenCalledTimes(1);
    return mockFetch.mock.calls[0]![0] as Request;
  }

  const SHA = "a".repeat(40);

  it("create POSTs the request and prints the receipt, warning the list may lag", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse(
        {
          eval_id: "eval-minted",
          name: "Refactor",
          goal: "Keep tests green",
          starting_workflow_id: null,
          baseline_repos: [{ repository: "acme/app", requested_ref: "main", commit_sha: SHA }],
          tags: ["refactor"],
        },
        201,
      ),
    );

    await run("create")({
      positionals: [],
      values: { name: "Refactor", goal: "Keep tests green", repo: ["acme/app@main"], tag: ["Refactor"] },
    });

    const request = sent();
    expect(request.method).toBe("POST");
    expect(new URL(request.url).pathname).toMatch(/\/evals$/);
    expect(JSON.parse(await request.text())).toEqual({
      name: "Refactor",
      goal: "Keep tests green",
      starting_workflow_id: null,
      baseline_repos: [{ repository: "acme/app", requested_ref: "main" }],
      tags: ["Refactor"],
    });
    const out = stdout();
    expect(out).toContain("Created eval eval-minted");
    expect(out).toContain(`acme/app@main -> ${SHA}`);
    expect(out).toContain("may take a moment");
  });

  it("create refuses a missing --goal without calling the API", async () => {
    await expect(run("create")({ positionals: [], values: { name: "n" } })).rejects.toThrow(CLIError);
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("list sends the status and tag filters and prints each eval's run count", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        evals: [
          {
            eval_id: "eval-a", name: "Refactor", goal: "g", starting_workflow_id: null,
            baseline_repos: [], tags: [], frozen: true, archived: false,
            created_at: "2026-10-06T00:00:00Z", updated_at: null,
            run_count: 7, run_status_counts: { completed: 7 },
          },
        ],
        total: 1, page: 1, page_size: 50, status_counts: { active: 1 },
      }),
    );

    await run("list")({ positionals: [], values: { status: "active", tag: ["nightly"] } });

    const url = new URL(sent().url);
    expect(url.pathname).toMatch(/\/evals$/);
    expect(url.searchParams.get("status")).toBe("active");
    expect(url.searchParams.getAll("tag")).toEqual(["nightly"]);
    const out = stdout();
    expect(out).toContain("eval-a");
    expect(out).toContain("7");
  });

  it("list refuses an unknown --status without calling the API", async () => {
    await expect(run("list")({ positionals: [], values: { status: "frozen" } })).rejects.toThrow(CLIError);
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("show prints the baseline and the run tally", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        eval_id: "eval-a", name: "Refactor", goal: "Keep tests green", starting_workflow_id: "wf-1",
        baseline_repos: [{ repository: "acme/app", requested_ref: "v1", commit_sha: SHA }],
        tags: ["nightly"], frozen: true, archived: false, created_at: null, updated_at: null,
        run_count: 3, run_status_counts: { completed: 2, failed: 1 },
      }),
    );

    await run("show")({ positionals: ["eval-a"], values: {} });

    expect(new URL(sent().url).pathname).toMatch(/\/evals\/eval-a$/);
    const out = stdout();
    expect(out).toContain(`acme/app@v1 -> ${SHA}`);
    expect(out).toContain("run_count:            3 (completed: 2, failed: 1)");
  });

  it("runs reads the eval's runs route and lists the executions", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        items: [
          {
            execution_id: "exec-in-eval", started_at: null, completed_at: null,
            status: "completed", workflow_id: "wf-1", workflow_version: null,
            models: [{ phase_id: "verify", model: "claude-opus-5-5" }],
            total_cost_usd: "1.25", total_cost_display: "$1.25",
            duration_seconds: null, duration_display: "-",
            verdict: "PASS", score: 1, evidence_excerpt: "## PASS", scorer: "eval_suite.py",
            scorer_version: "2", scored_at: null,
          },
        ],
        total: 1, page: 1, page_size: 50,
      }),
    );

    await run("runs")({ positionals: ["eval-a"], values: {} });

    expect(new URL(sent().url).pathname).toMatch(/\/evals\/eval-a\/runs$/);
    const out = stdout();
    expect(out).toContain("exec-in-eval");
    expect(out).toContain("claude-opus-5-5");
    expect(out).toContain("PASS");
  });

  it("archive POSTs to the archive route", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ eval_id: "eval-a", archived: true }));

    await run("archive")({ positionals: ["eval-a"], values: {} });

    const request = sent();
    expect(request.method).toBe("POST");
    expect(new URL(request.url).pathname).toMatch(/\/evals\/eval-a\/archive$/);
    expect(stdout()).toContain("Archived eval eval-a");
  });

  it("surfaces the server's 404 for an eval the read model does not hold", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ detail: "Eval not found: eval-x" }, 404));

    await expect(run("show")({ positionals: ["eval-x"], values: {} })).rejects.toThrow("Eval not found");
  });

  it.each(["acme/app", "acme/app@", "@main"])("parseBaselineRepo refuses %s", (spec) => {
    expect(() => parseBaselineRepo(spec)).toThrow(CLIError);
  });

  it("parseBaselineRepo splits on the first @: a slug has none, a ref may", () => {
    expect(parseBaselineRepo("acme/app@release@2")).toEqual({
      repository: "acme/app",
      requested_ref: "release@2",
    });
  });
});
