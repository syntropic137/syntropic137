import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { artifactsGroup } from "../../src/commands/artifacts.js";
import { CLIError } from "../../src/framework/errors.js";

describe("artifacts commands", () => {
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

  describe("list", () => {
    const handler = artifactsGroup.getCommand("list")!.handler;

    /**
     * One page of the envelope /artifacts answers with since #1204. Field
     * names are the ArtifactListResponse model's, verbatim — the endpoint
     * returned a bare array before, and a fixture still shaped like one is
     * how a client that never learned the difference keeps passing.
     */
    function artifactPage(
      artifacts: unknown[],
      { total, page = 1, pageSize = 50 }: { total: number; page?: number; pageSize?: number },
    ): Response {
      return jsonResponse({ artifacts, total, page, page_size: pageSize, type_counts: {} });
    }

    it("renders artifacts table", async () => {
      mockFetch.mockResolvedValue(
        artifactPage(
          [
            {
              id: "art-001-abcdef123456",
              artifact_type: "code",
              title: "my-artifact",
              size_bytes: 2048,
              created_at: "2026-01-01T00:00:00Z",
            },
          ],
          { total: 137 },
        ),
      );

      await handler({ positionals: [], values: {} });
      const out = stdout();
      expect(out).toContain("art-001-abcd");
      expect(out).toContain("code");
      expect(out).toContain("my-artifact");
      expect(out).toContain("2KB");
    });

    it("shows empty message when no artifacts", async () => {
      mockFetch.mockResolvedValue(artifactPage([], { total: 0 }));
      await handler({ positionals: [], values: {} });
      expect(stdout()).toContain("No artifacts found");
    });

    it("formats small sizes in bytes", async () => {
      mockFetch.mockResolvedValue(
        artifactPage(
          [
            {
              id: "art-002-abcdef123456",
              artifact_type: "text",
              title: "tiny",
              size_bytes: 512,
              created_at: "2026-01-01T00:00:00Z",
            },
          ],
          { total: 1 },
        ),
      );

      await handler({ positionals: [], values: {} });
      expect(stdout()).toContain("512B");
    });

    it("reports the collection total, not the number of rows on the page", async () => {
      mockFetch.mockResolvedValue(
        artifactPage(
          [
            {
              id: "art-003-abcdef123456",
              artifact_type: "code",
              title: "one-of-many",
              size_bytes: 10,
              created_at: "2026-01-01T00:00:00Z",
            },
          ],
          { total: 137 },
        ),
      );

      await handler({ positionals: [], values: {} });
      const out = stdout();
      expect(out).toContain("137 total");
      expect(out).not.toContain("1 total");
      expect(out).toContain("Use --page 2 for more.");
    });

    it("omits the next-page hint once the page reaches the end of the collection", async () => {
      mockFetch.mockResolvedValue(
        artifactPage(
          [
            {
              id: "art-004-abcdef123456",
              artifact_type: "code",
              title: "last-page",
              size_bytes: 10,
              created_at: "2026-01-01T00:00:00Z",
            },
          ],
          { total: 137, page: 3 },
        ),
      );

      await handler({ positionals: [], values: { page: "3" } });
      const out = stdout();
      expect(out).toContain("137 total");
      expect(out).not.toContain("Use --page");
    });
  });

  describe("show", () => {
    const handler = artifactsGroup.getCommand("show")!.handler;

    it("renders artifact detail", async () => {
      mockFetch.mockResolvedValue(
        jsonResponse({
          id: "art-001",
          artifact_type: "markdown",
          title: "Test Artifact",
          workflow_id: "wf-123",
          phase_id: "ph-1",
          created_at: "2026-01-01T00:00:00Z",
          size_bytes: 1024,
          content: "Hello world",
        }),
      );

      await handler({ positionals: ["art-001"], values: {} });
      const out = stdout();
      expect(out).toContain("art-001");
      expect(out).toContain("markdown");
      expect(out).toContain("Test Artifact");
      expect(out).toContain("wf-123");
      expect(out).toContain("Hello world");
    });

    it("throws on missing artifact-id", async () => {
      await expect(handler({ positionals: [], values: {} })).rejects.toThrow(CLIError);
    });
  });

  describe("content", () => {
    const handler = artifactsGroup.getCommand("content")!.handler;

    it("prints artifact content", async () => {
      mockFetch.mockResolvedValue(
        jsonResponse({ content: "raw content here" }),
      );

      await handler({ positionals: ["art-001"], values: {} });
      expect(stdout()).toContain("raw content here");
    });

    it("shows no-content message when empty", async () => {
      mockFetch.mockResolvedValue(jsonResponse({ content: null }));
      await handler({ positionals: ["art-001"], values: {} });
      expect(stdout()).toContain("no content");
    });

    it("throws on missing artifact-id", async () => {
      await expect(handler({ positionals: [], values: {} })).rejects.toThrow(CLIError);
    });
  });

  describe("create", () => {
    const handler = artifactsGroup.getCommand("create")!.handler;

    it("renders created artifact", async () => {
      mockFetch.mockResolvedValue(
        jsonResponse({
          id: "art-new-001",
          artifact_type: "code",
          title: "New Artifact",
        }),
      );

      await handler({
        positionals: [],
        values: { workflow: "wf-1", type: "code", title: "New Artifact", content: "some code" },
      });
      const out = stdout();
      expect(out).toContain("Created artifact");
      expect(out).toContain("New Artifact");
      expect(out).toContain("art-new-001");
    });
  });
});
