import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { evalGroup } from "../../src/commands/eval.js";
import { CLIError } from "../../src/framework/errors.js";

describe("syn eval attach|detach (#967)", () => {
  const mockFetch = vi.fn();
  const attach = evalGroup.getCommand("attach")!.handler;
  const detach = evalGroup.getCommand("detach")!.handler;

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

  it("attach POSTs the eval as a body and prints the server's membership", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        execution_id: "exec-full-id",
        eval_id: "eval-a",
        association_kind: "attached",
        launched_eval_id: null,
      }),
    );

    await attach({ positionals: ["exec-full", "eval-a"], values: {} });

    const request = sent();
    expect(request.method).toBe("POST");
    expect(new URL(request.url).pathname).toMatch(/\/executions\/exec-full\/eval$/);
    expect(JSON.parse(await request.text())).toEqual({ eval_id: "eval-a" });
    const out = stdout();
    expect(out).toContain("exec-full-id");
    expect(out).toContain("eval_id:          eval-a");
    expect(out).toContain("association_kind: attached");
    expect(out).toContain("launched_eval_id: (none)");
  });

  it("detach DELETEs with ?eval_id= and prints the kept launch record", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        execution_id: "exec-full-id",
        eval_id: null,
        association_kind: null,
        launched_eval_id: "eval-a",
      }),
    );

    await detach({ positionals: ["exec-full", "eval-a"], values: {} });

    const request = sent();
    expect(request.method).toBe("DELETE");
    const url = new URL(request.url);
    expect(url.pathname).toMatch(/\/executions\/exec-full\/eval$/);
    expect(url.searchParams.get("eval_id")).toBe("eval-a");
    const out = stdout();
    expect(out).toContain("eval_id:          (none)");
    expect(out).toContain("launched_eval_id: eval-a");
  });

  it("surfaces the server's 409 for a run in another eval", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ detail: "Execution exec-1 belongs to eval eval-a; detach it before attaching it to eval-b" }, 409),
    );

    await expect(attach({ positionals: ["exec-1", "eval-b"], values: {} })).rejects.toThrow(
      "detach it before attaching it to eval-b",
    );
  });

  it("surfaces the server's 409 for an archived eval", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ detail: "Eval eval-a is archived and cannot take runs" }, 409),
    );

    await expect(attach({ positionals: ["exec-1", "eval-a"], values: {} })).rejects.toThrow(
      "is archived and cannot take runs",
    );
  });

  it.each([[[]], [["exec-1"]]])("refuses %j without calling the API", async (positionals) => {
    await expect(attach({ positionals, values: {} })).rejects.toThrow(CLIError);
    await expect(detach({ positionals, values: {} })).rejects.toThrow(CLIError);
    expect(mockFetch).not.toHaveBeenCalled();
  });
});
