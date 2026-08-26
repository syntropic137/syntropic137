/**
 * Resolving a workflow id must not depend on where it falls in a page.
 *
 * Issue #880: `syn workflow run <id>` listed workflows and matched
 * client-side against a default page of 20. On a stack with more than 20
 * workflows, anything past the first page reported "No workflow found
 * matching" - the one message guaranteed to send a user off reinstalling
 * something that was already installed correctly. It is also silent and
 * gets worse the longer the platform is used.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resolveWorkflow } from "../../../src/commands/workflow/resolver.js";

const mockFetch = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", mockFetch);
  vi.spyOn(process.stdout, "write").mockReturnValue(true);
  vi.spyOn(process.stderr, "write").mockReturnValue(true);
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function summary(id: string) {
  return { id, name: id, workflow_type: "research", phase_count: 1 };
}

describe("resolveWorkflow", () => {
  it("resolves an exact id via the detail endpoint without listing", async () => {
    mockFetch.mockResolvedValueOnce(
      json({ id: "skillproof-research-v1", name: "Skill Proof", workflow_type: "research", phases: [{}, {}] }),
    );

    const wf = await resolveWorkflow("skillproof-research-v1");

    expect(wf.id).toBe("skillproof-research-v1");
    expect(wf.phase_count).toBe(2);
    expect(mockFetch).toHaveBeenCalledTimes(1);
    const first = mockFetch.mock.calls[0]![0] as Request | string;
    const url = typeof first === "string" ? first : first.url;
    expect(url).toContain("/workflows/skillproof-research-v1");
  });

  it("finds a workflow that falls past the first page", async () => {
    // Detail lookup misses because the caller passed a prefix.
    mockFetch.mockResolvedValueOnce(json({ detail: "Not found" }, 404));
    // Page 1 is full and does not contain the target; page 2 does.
    const page1 = Array.from({ length: 100 }, (_, i) => summary(`filler-${i}`));
    mockFetch.mockResolvedValueOnce(json({ workflows: page1 }));
    mockFetch.mockResolvedValueOnce(json({ workflows: [summary("late-arrival-wf")] }));

    const wf = await resolveWorkflow("late-arrival");

    expect(wf.id).toBe("late-arrival-wf");
    expect(mockFetch).toHaveBeenCalledTimes(3);
  });

  it("stops paging on a short page", async () => {
    mockFetch.mockResolvedValueOnce(json({ detail: "Not found" }, 404));
    mockFetch.mockResolvedValueOnce(json({ workflows: [summary("only-one")] }));

    const wf = await resolveWorkflow("only");

    expect(wf.id).toBe("only-one");
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });

  it("reports how many workflows it actually searched when nothing matches", async () => {
    mockFetch.mockResolvedValueOnce(json({ detail: "Not found" }, 404));
    mockFetch.mockResolvedValueOnce(json({ workflows: [summary("alpha"), summary("beta")] }));

    await expect(resolveWorkflow("nope")).rejects.toThrow(/Workflow not found/);
  });
});
