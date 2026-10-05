/**
 * Prune archives only what the SERVER attributes to the package (issue #1588).
 *
 * Local history (installed.json) nominated `sdlc-implement-v3` under a
 * colliding package name and the CLI sent DELETE for it. These tests drive
 * the HTTP the prune actually issues: the GET that reads the server's
 * provenance, and whether a DELETE is ever sent.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const question = vi.fn();
vi.mock("node:readline/promises", () => ({
  default: { createInterface: () => ({ question, close: () => undefined }) },
}));

import { pruneWorkflows } from "../../../src/commands/workflow/prune.js";
import { CLIError } from "../../../src/framework/errors.js";

const mockFetch = vi.fn();
const stdout: string[] = [];
const originalStdinTTY = process.stdin.isTTY;
const originalStdoutTTY = process.stdout.isTTY;

function setTTY(value: boolean): void {
  Object.defineProperty(process.stdin, "isTTY", { value, configurable: true });
  Object.defineProperty(process.stdout, "isTTY", { value, configurable: true });
}

beforeEach(() => {
  vi.stubGlobal("fetch", mockFetch);
  stdout.length = 0;
  vi.spyOn(process.stdout, "write").mockImplementation((chunk) => {
    stdout.push(String(chunk));
    return true;
  });
  vi.spyOn(process.stderr, "write").mockImplementation((chunk) => {
    stdout.push(String(chunk));
    return true;
  });
  setTTY(false);
});

afterEach(() => {
  vi.restoreAllMocks();
  mockFetch.mockReset();
  question.mockReset();
  vi.unstubAllGlobals();
  Object.defineProperty(process.stdin, "isTTY", { value: originalStdinTTY, configurable: true });
  Object.defineProperty(process.stdout, "isTTY", { value: originalStdoutTTY, configurable: true });
});

const V3 = { id: "sdlc-implement-v3", name: "SDLC Implement v3" };
const OLD = { id: "implement-old", name: "Implement (old)" };

/** Server: GET returns each workflow with the package the server records. */
function server(owners: Record<string, string | null>, deleteStatus = 204, deleteBody = ""): void {
  mockFetch.mockImplementation(async (input: Request) => {
    const id = decodeURIComponent(new URL(input.url).pathname.split("/").pop()!);
    if (input.method === "DELETE") {
      return new Response(deleteBody || null, {
        status: deleteStatus,
        headers: deleteBody ? { "Content-Type": "application/json" } : {},
      });
    }
    if (!(id in owners)) return new Response(JSON.stringify({ detail: "nf" }), { status: 404 });
    return new Response(
      JSON.stringify({ id, name: id, workflow_type: "custom", classification: "standard", package_name: owners[id] }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  });
}

function deletes(): string[] {
  return mockFetch.mock.calls
    .map((c) => c[0] as Request)
    .filter((r) => r.method === "DELETE")
    .map((r) => decodeURIComponent(new URL(r.url).pathname.split("/").pop()!));
}

describe("pruneWorkflows", () => {
  it("archives nothing the server attributes to another package, even with --prune --yes", async () => {
    // The 2026-10-05 near miss: local history lists sdlc-implement-v3 under
    // `implement`, but the server records it as installed by `implement-v3`.
    server({ [V3.id]: "implement-v3" });

    const result = await pruneWorkflows([V3], { packageName: "implement", prune: true, yes: true });

    expect(deletes()).toEqual([]);
    expect(result).toEqual({ archived: [], retained: [], failed: [] });
    expect(stdout.join("")).toContain("server records it as installed by package 'implement-v3'");
  });

  it("archives nothing the server has no provenance for", async () => {
    server({ [V3.id]: null });
    await pruneWorkflows([V3], { packageName: "implement", prune: true, yes: true });
    expect(deletes()).toEqual([]);
  });

  it("archives a workflow the server attributes to this package with --prune --yes", async () => {
    server({ [OLD.id]: "implement", [V3.id]: "implement-v3" });

    const result = await pruneWorkflows([OLD, V3], { packageName: "implement", prune: true, yes: true });

    expect(deletes()).toEqual([OLD.id]);
    expect(result.archived).toEqual([OLD]);
  });

  it("without --prune lists the workflow and archives nothing, keeping it tracked", async () => {
    server({ [OLD.id]: "implement" });

    const result = await pruneWorkflows([OLD], { packageName: "implement", prune: false, yes: false });

    expect(deletes()).toEqual([]);
    expect(result.retained).toEqual([OLD]);
    expect(stdout.join("")).toContain("--prune");
  });

  it("skips a workflow with running executions and says so", async () => {
    server(
      { [OLD.id]: "implement" },
      409,
      JSON.stringify({ detail: "Cannot archive: 1 active execution(s) in progress" }),
    );

    const result = await pruneWorkflows([OLD], { packageName: "implement", prune: true, yes: true });

    expect(deletes()).toEqual([OLD.id]);
    expect(result).toEqual({ archived: [], retained: [OLD], failed: [] });
    expect(stdout.join("")).toContain("skipped: it has running executions");
  });

  it("treats a 409 'already archived' as archived, not as running", async () => {
    server({ [OLD.id]: "implement" }, 409, JSON.stringify({ detail: "Workflow is already archived" }));
    const result = await pruneWorkflows([OLD], { packageName: "implement", prune: true, yes: true });
    expect(result.archived).toEqual([OLD]);
  });

  it("--prune without --yes on a non-TTY refuses before sending any DELETE", async () => {
    server({ [OLD.id]: "implement" });

    await expect(
      pruneWorkflows([OLD], { packageName: "implement", prune: true, yes: false }),
    ).rejects.toThrow(CLIError);
    expect(deletes()).toEqual([]);
    expect(question).not.toHaveBeenCalled();
  });

  it("--prune without --yes on a TTY lists, asks, and archives nothing on 'no'", async () => {
    setTTY(true);
    server({ [OLD.id]: "implement" });
    question.mockResolvedValue("n");

    const result = await pruneWorkflows([OLD], { packageName: "implement", prune: true, yes: false });

    expect(question).toHaveBeenCalledOnce();
    expect(stdout.join("")).toContain(OLD.name);
    expect(deletes()).toEqual([]);
    expect(result.retained).toEqual([OLD]);
  });

  it("--prune without --yes on a TTY archives on 'y'", async () => {
    setTTY(true);
    server({ [OLD.id]: "implement" });
    question.mockResolvedValue("y");

    await pruneWorkflows([OLD], { packageName: "implement", prune: true, yes: false });

    expect(deletes()).toEqual([OLD.id]);
  });
});
