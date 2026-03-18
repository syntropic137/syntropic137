import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SyntropicClient, resolveConfig } from "../src/client.js";

// ---------------------------------------------------------------------------
// Mock fetch
// ---------------------------------------------------------------------------

const mockFetch = vi.fn<typeof globalThis.fetch>();

beforeEach(() => {
  vi.stubGlobal("fetch", mockFetch);
});

afterEach(() => {
  vi.restoreAllMocks();
});

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    statusText: status === 200 ? "OK" : "Error",
    headers: { "Content-Type": "application/json" },
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("SyntropicClient", () => {
  it("GET request sends correct URL and headers", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ ok: true }));

    const client = new SyntropicClient({ apiUrl: "http://localhost:8000", apiKey: "test-key" });
    await client.get("/workflows");

    expect(mockFetch).toHaveBeenCalledOnce();
    const [url, init] = mockFetch.mock.calls[0]!;
    expect(url).toBe("http://localhost:8000/workflows");
    expect((init as RequestInit).method).toBe("GET");
    expect((init as RequestInit).headers).toMatchObject({
      Authorization: "Bearer test-key",
    });
  });

  it("GET with query params", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ ok: true }));

    const client = new SyntropicClient({ apiUrl: "http://localhost:8000" });
    await client.get("/workflows", { workflow_type: "issue", page: "2" });

    const [url] = mockFetch.mock.calls[0]!;
    const parsed = new URL(url as string);
    expect(parsed.searchParams.get("workflow_type")).toBe("issue");
    expect(parsed.searchParams.get("page")).toBe("2");
  });

  it("POST sends JSON body", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ execution_id: "e1" }));

    const client = new SyntropicClient({ apiUrl: "http://localhost:8000" });
    await client.post("/workflows/wf-1/execute", { inputs: { url: "https://example.com" } });

    const [, init] = mockFetch.mock.calls[0]!;
    expect((init as RequestInit).method).toBe("POST");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      inputs: { url: "https://example.com" },
    });
  });

  it("returns ok: true on success", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ value: 42 }));

    const client = new SyntropicClient({ apiUrl: "http://localhost:8000" });
    const result = await client.get<{ value: number }>("/test");

    expect(result.ok).toBe(true);
    if (result.ok) expect(result.data.value).toBe(42);
  });

  it("returns ok: false on HTTP error", async () => {
    mockFetch.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Not found" }), { status: 404, statusText: "Not Found" }),
    );

    const client = new SyntropicClient({ apiUrl: "http://localhost:8000" });
    const result = await client.get("/missing");

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.status).toBe(404);
      expect(result.error.message).toBe("Not found");
    }
  });

  it("returns ok: false on network error", async () => {
    mockFetch.mockRejectedValueOnce(new Error("ECONNREFUSED"));

    const client = new SyntropicClient({ apiUrl: "http://localhost:8000" });
    const result = await client.get("/test");

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.status).toBe(0);
      expect(result.error.message).toContain("ECONNREFUSED");
    }
  });

  it("strips trailing slash from apiUrl", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({}));

    const client = new SyntropicClient({ apiUrl: "http://localhost:8000/" });
    await client.get("/workflows");

    const [url] = mockFetch.mock.calls[0]!;
    expect(url).toBe("http://localhost:8000/workflows");
  });
});

describe("resolveConfig", () => {
  it("uses plugin config over env", () => {
    const config = resolveConfig({ apiUrl: "http://custom:9000", apiKey: "key1" });
    expect(config.apiUrl).toBe("http://custom:9000");
    expect(config.apiKey).toBe("key1");
  });

  it("falls back to env vars", () => {
    const origUrl = process.env["SYNTROPIC_URL"];
    const origKey = process.env["SYNTROPIC_API_KEY"];
    try {
      process.env["SYNTROPIC_URL"] = "http://env:7000";
      process.env["SYNTROPIC_API_KEY"] = "env-key";
      const config = resolveConfig({});
      expect(config.apiUrl).toBe("http://env:7000");
      expect(config.apiKey).toBe("env-key");
    } finally {
      if (origUrl === undefined) delete process.env["SYNTROPIC_URL"];
      else process.env["SYNTROPIC_URL"] = origUrl;
      if (origKey === undefined) delete process.env["SYNTROPIC_API_KEY"];
      else process.env["SYNTROPIC_API_KEY"] = origKey;
    }
  });

  it("defaults to localhost:8000", () => {
    const origUrl = process.env["SYNTROPIC_URL"];
    try {
      delete process.env["SYNTROPIC_URL"];
      const config = resolveConfig();
      expect(config.apiUrl).toBe("http://localhost:8000");
      expect(config.apiKey).toBeUndefined();
    } finally {
      if (origUrl !== undefined) process.env["SYNTROPIC_URL"] = origUrl;
    }
  });
});
