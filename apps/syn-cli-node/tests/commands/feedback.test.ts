import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { feedbackGroup } from "../../src/commands/feedback.js";

describe("feedback commands", () => {
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

  function requestedUrl(): URL {
    return new URL((mockFetch.mock.calls[0]![0] as Request).url);
  }

  const item = {
    id: "3f2c1b4a-0000-4000-8000-000000000001",
    url: "http://localhost:9137/executions/exec-1",
    route: "/executions/exec-1",
    feedback_type: "bug",
    comment: "The phase timer keeps running after it finishes.",
    status: "open",
    priority: "medium",
    app_name: "syn-dashboard-ui",
    created_at: "2026-09-18T10:00:00Z",
    updated_at: "2026-09-18T10:00:00Z",
    media_count: 1,
  };

  it("list renders the items it was given", async () => {
    mockFetch.mockResolvedValue(jsonResponse({ items: [item], total: 1, page: 1, page_size: 50 }));

    await feedbackGroup.getCommand("list")!.handler({ positionals: [], values: {} });

    const out = stdout();
    expect(out).toContain("3f2c1b4a-000");
    expect(out).toContain("open");
    expect(out).toContain("/executions/exec-1");
    expect(out).toContain("phase timer");
  });

  it("list sends the triage filters as query parameters", async () => {
    mockFetch.mockResolvedValue(jsonResponse({ items: [], total: 0, page: 1, page_size: 50 }));

    await feedbackGroup.getCommand("list")!.handler({
      positionals: [],
      values: { status: "open", type: "bug", route: "/executions", execution: "exec-1" },
    });

    const query = requestedUrl().searchParams;
    expect(query.get("status")).toBe("open");
    expect(query.get("type")).toBe("bug");
    expect(query.get("route")).toBe("/executions");
    expect(query.get("subject_id")).toBe("exec-1");
    // --execution is sugar for a subject; the kind has to travel with the id.
    expect(query.get("subject_kind")).toBe("execution");
  });

  it("list reports the feature being disabled instead of failing", async () => {
    mockFetch.mockResolvedValue(
      jsonResponse(
        {
          detail: {
            feature: "ui_feedback",
            reason: "The in-app feedback feature is disabled on this deployment.",
            enable_with: "SYN_UI_FEEDBACK_ENABLED=true",
          },
        },
        404,
      ),
    );

    await feedbackGroup.getCommand("list")!.handler({ positionals: [], values: {} });

    expect(stdout()).toContain("SYN_UI_FEEDBACK_ENABLED=true");
  });
});
