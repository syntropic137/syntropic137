import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { executionGroup } from "../../src/commands/execution.js";
import { CLIError } from "../../src/framework/errors.js";

describe("syn execution tag (#967)", () => {
  const mockFetch = vi.fn();
  const handler = executionGroup.getCommand("tag")!.handler;

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

  const answer = {
    execution_id: "exec-full-id",
    tags: ["eval:x", "smoke"],
    inherited_tags: ["nightly", "smoke"],
  };

  it("add POSTs the tags as a body and prints the server's set", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(answer));

    await handler({ positionals: ["add", "exec-full", "eval:x", "smoke"], values: {} });

    const request = sent();
    expect(request.method).toBe("POST");
    expect(new URL(request.url).pathname).toMatch(/\/executions\/exec-full\/tags$/);
    expect(JSON.parse(await request.text())).toEqual({ tags: ["eval:x", "smoke"] });
    const out = stdout();
    expect(out).toContain("exec-full-id");
    expect(out).toContain("tags:           eval:x, smoke");
    expect(out).toContain("inherited_tags: nightly, smoke");
  });

  it("remove DELETEs with one ?tag= per tag, matching the list filter", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ ...answer, tags: [] }));

    await handler({ positionals: ["remove", "exec-full", "eval:x", "smoke"], values: {} });

    const request = sent();
    expect(request.method).toBe("DELETE");
    const url = new URL(request.url);
    expect(url.pathname).toMatch(/\/executions\/exec-full\/tags$/);
    expect(url.searchParams.getAll("tag")).toEqual(["eval:x", "smoke"]);
    expect(stdout()).toContain("tags:           (none)");
  });

  it("surfaces the server's 422 detail", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ detail: "Invalid tag 'has space'" }, 422));

    await expect(
      handler({ positionals: ["add", "exec-full", "has space"], values: {} }),
    ).rejects.toThrow("Invalid tag 'has space'");
  });

  it("surfaces a 404 for an unknown execution", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ detail: "Execution not found: nope" }, 404));

    await expect(handler({ positionals: ["remove", "nope", "x"], values: {} })).rejects.toThrow(
      "Execution not found: nope",
    );
  });

  it.each([
    [[]],
    [["replace", "exec-1", "x"]],
    [["add", "exec-1"]],
    [["add"]],
  ])("refuses %j without calling the API", async (positionals) => {
    await expect(handler({ positionals, values: {} })).rejects.toThrow(CLIError);
    expect(mockFetch).not.toHaveBeenCalled();
  });
});
