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

  /** The workflow detail the resolver reads first, then the tag edit's answer. */
  function serve(tags: string[]): void {
    mockFetch
      .mockResolvedValueOnce(
        jsonResponse({ id: "wf-full-id", name: "Evals", workflow_type: "research", phases: [] }),
      )
      .mockResolvedValueOnce(jsonResponse({ workflow_id: "wf-full-id", tags }));
  }

  function editRequest(): Request {
    expect(mockFetch).toHaveBeenCalledTimes(2);
    return mockFetch.mock.calls[1]![0] as Request;
  }

  it("add resolves the id, POSTs the tags and prints the server's set", async () => {
    serve(["nightly", "team:evals"]);

    await handler({ positionals: ["add", "wf-full-id", "Team:Evals", "nightly"], values: {} });

    const request = editRequest();
    expect(request.method).toBe("POST");
    expect(new URL(request.url).pathname).toMatch(/\/workflows\/wf-full-id\/tags$/);
    expect(JSON.parse(await request.text())).toEqual({ tags: ["Team:Evals", "nightly"] });
    expect(stdout()).toContain("tags: nightly, team:evals");
  });

  it("remove DELETEs with one ?tag= per tag against the resolved id", async () => {
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
    mockFetch
      .mockResolvedValueOnce(jsonResponse({ id: "wf-full-id", name: "Evals", workflow_type: "research", phases: [] }))
      .mockResolvedValueOnce(jsonResponse({ detail: "Invalid tag 'bad tag!'" }, 422));

    await expect(
      handler({ positionals: ["add", "wf-full-id", "bad tag!"], values: {} }),
    ).rejects.toThrow("Invalid tag 'bad tag!'");
  });

  it.each([[["add", "wf-1"]], [["tag", "wf-1", "x"]]])(
    "refuses %j without calling the API",
    async (positionals) => {
      await expect(handler({ positionals, values: {} })).rejects.toThrow(CLIError);
      expect(mockFetch).not.toHaveBeenCalled();
    },
  );
});
