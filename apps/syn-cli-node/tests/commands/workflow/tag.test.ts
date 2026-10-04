import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { workflowGroup } from "../../../src/commands/workflow/index.js";
import { CLIError } from "../../../src/framework/errors.js";

describe("syn workflow tag (#967)", () => {
  const mockFetch = vi.fn();
  const handler = workflowGroup.getCommand("tag")!.handler;

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

  /** The tag edit's answer: the route resolves the id itself, so no read first. */
  function serve(tags: string[]): void {
    mockFetch.mockResolvedValueOnce(jsonResponse({ workflow_id: "wf-full-id", tags }));
  }

  function editRequest(): Request {
    expect(mockFetch).toHaveBeenCalledTimes(1);
    return mockFetch.mock.calls[0]![0] as Request;
  }

  it("add POSTs the tags and prints the server's set", async () => {
    serve(["nightly", "team:evals"]);

    await handler({ positionals: ["add", "wf-full-id", "Team:Evals", "nightly"], values: {} });

    const request = editRequest();
    expect(request.method).toBe("POST");
    expect(new URL(request.url).pathname).toMatch(/\/workflows\/wf-full-id\/tags$/);
    expect(JSON.parse(await request.text())).toEqual({ tags: ["Team:Evals", "nightly"] });
    expect(stdout()).toContain("tags: nightly, team:evals");
  });

  it("remove DELETEs with one ?tag= per tag against the given id", async () => {
    serve(["team:evals"]);

    await handler({ positionals: ["remove", "wf-full-id", "nightly"], values: {} });

    const request = editRequest();
    expect(request.method).toBe("DELETE");
    const url = new URL(request.url);
    expect(url.pathname).toMatch(/\/workflows\/wf-full-id\/tags$/);
    expect(url.searchParams.getAll("tag")).toEqual(["nightly"]);
    expect(stdout()).toContain("tags: team:evals");
  });

  it("surfaces the server's 422 detail", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ detail: "Invalid tag 'bad tag!'" }, 422));

    await expect(
      handler({ positionals: ["add", "wf-full-id", "bad tag!"], values: {} }),
    ).rejects.toThrow("Invalid tag 'bad tag!'");
  });

  it("edits an exact id whose read models have not caught up yet", async () => {
    // Only the tag route answers; any projection read would get a 404 / empty list.
    mockFetch.mockImplementation(async (request: Request) => {
      if (new URL(request.url).pathname.endsWith("/workflows/wf-new-id/tags")) {
        return jsonResponse({ workflow_id: "wf-new-id", tags: ["nightly"] });
      }
      return request.url.includes("/workflows/wf-new-id")
        ? jsonResponse({ detail: "Workflow not found" }, 404)
        : jsonResponse({ workflows: [], total: 0 });
    });

    await handler({ positionals: ["add", "wf-new-id", "nightly"], values: {} });

    const request = editRequest();
    expect(request.method).toBe("POST");
    expect(new URL(request.url).pathname).toMatch(/\/workflows\/wf-new-id\/tags$/);
    expect(stdout()).toContain("Tags of wf-new-id");
    expect(stdout()).toContain("tags: nightly");
  });

  it("after the route's 404, retries with the id the resolver finds", async () => {
    mockFetch
      .mockResolvedValueOnce(jsonResponse({ detail: "workflow not found: evals" }, 404))
      .mockResolvedValueOnce(jsonResponse({ detail: "Workflow not found" }, 404))
      .mockResolvedValueOnce(
        jsonResponse({ workflows: [{ id: "evals-wf-full", name: "Evals", workflow_type: "research" }], total: 1 }),
      )
      .mockResolvedValueOnce(jsonResponse({ workflow_id: "evals-wf-full", tags: ["nightly"] }));

    await handler({ positionals: ["add", "evals", "nightly"], values: {} });

    expect(mockFetch).toHaveBeenCalledTimes(4);
    const retry = mockFetch.mock.calls[3]![0] as Request;
    expect(retry.method).toBe("POST");
    expect(new URL(retry.url).pathname).toMatch(/\/workflows\/evals-wf-full\/tags$/);
    expect(stdout()).toContain("Tags of evals-wf-full");
  });

  it("reports not found when neither the route nor the resolver knows the id", async () => {
    mockFetch
      .mockResolvedValueOnce(jsonResponse({ detail: "workflow not found: nope" }, 404))
      .mockResolvedValueOnce(jsonResponse({ detail: "Workflow not found" }, 404))
      .mockResolvedValueOnce(jsonResponse({ workflows: [], total: 0 }));

    await expect(handler({ positionals: ["add", "nope", "x"], values: {} })).rejects.toThrow("Workflow not found");
    expect(mockFetch).toHaveBeenCalledTimes(3);
  });

  it.each([[["add", "wf-1"]], [["tag", "wf-1", "x"]]])(
    "refuses %j without calling the API",
    async (positionals) => {
      await expect(handler({ positionals, values: {} })).rejects.toThrow(CLIError);
      expect(mockFetch).not.toHaveBeenCalled();
    },
  );
});
