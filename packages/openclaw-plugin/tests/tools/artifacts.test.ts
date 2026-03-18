import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SyntropicClient } from "../../src/client.js";
import { synGetArtifact, synListArtifacts } from "../../src/tools/artifacts.js";
import { artifactDetail, artifactList } from "../fixtures/responses.js";

const mockFetch = vi.fn<typeof globalThis.fetch>();
let client: SyntropicClient;

beforeEach(() => {
  vi.stubGlobal("fetch", mockFetch);
  client = new SyntropicClient({ apiUrl: "http://localhost:8137" });
});

afterEach(() => {
  vi.restoreAllMocks();
});

function jsonResponse(data: unknown): Response {
  return new Response(JSON.stringify(data), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("synListArtifacts", () => {
  it("returns formatted artifact list", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(artifactList));

    const result = await synListArtifacts(client, {});

    expect(result.isError).toBeUndefined();
    expect(result.content).toContain("Issue Analysis Report");
    expect(result.content).toContain("art-001");
    expect(result.content).toContain("4.0 KB");
  });

  it("handles empty list", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse([]));

    const result = await synListArtifacts(client, {});
    expect(result.content).toBe("No artifacts found.");
  });

  it("passes filter params", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(artifactList));

    await synListArtifacts(client, { workflow_id: "wf-001", artifact_type: "analysis" });

    const [url] = mockFetch.mock.calls[0]!;
    const parsed = new URL(url as string);
    expect(parsed.searchParams.get("workflow_id")).toBe("wf-001");
    expect(parsed.searchParams.get("artifact_type")).toBe("analysis");
  });
});

describe("synGetArtifact", () => {
  it("returns formatted artifact with content", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(artifactDetail));

    const result = await synGetArtifact(client, { artifact_id: "art-001" });

    expect(result.isError).toBeUndefined();
    expect(result.content).toContain("Issue Analysis Report");
    expect(result.content).toContain("text/markdown");
    expect(result.content).toContain("null check missing");
  });

  it("handles 404", async () => {
    mockFetch.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Not found" }), { status: 404 }),
    );

    const result = await synGetArtifact(client, { artifact_id: "nonexistent" });
    expect(result.isError).toBe(true);
  });
});
