import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SynClient } from "../../src/client/http.js";

describe("SynClient", () => {
  const mockFetch = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("fetch", mockFetch);
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

  it("makes GET requests with correct URL", async () => {
    mockFetch.mockResolvedValue(jsonResponse({ ok: true }));
    const client = new SynClient({ baseUrl: "http://test:8000" });

    const result = await client.get("/health");

    expect(result.status).toBe(200);
    expect(result.data).toEqual({ ok: true });
    expect(mockFetch).toHaveBeenCalledOnce();
    const url = mockFetch.mock.calls[0]![0] as string;
    expect(url).toBe("http://test:8000/api/v1/health");
  });

  it("appends query params and filters undefined", async () => {
    mockFetch.mockResolvedValue(jsonResponse([]));
    const client = new SynClient({ baseUrl: "http://test:8000" });

    await client.get("/items", { limit: 10, offset: undefined });

    const url = mockFetch.mock.calls[0]![0] as string;
    expect(url).toContain("limit=10");
    expect(url).not.toContain("offset");
  });

  it("sends POST with JSON body", async () => {
    mockFetch.mockResolvedValue(jsonResponse({ id: "123" }, 201));
    const client = new SynClient({ baseUrl: "http://test:8000" });

    const result = await client.post("/items", { name: "test" });

    expect(result.status).toBe(201);
    const init = mockFetch.mock.calls[0]![1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(init.body).toBe('{"name":"test"}');
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe(
      "application/json",
    );
  });

  it("sends PUT with JSON body", async () => {
    mockFetch.mockResolvedValue(jsonResponse({ updated: true }));
    const client = new SynClient({ baseUrl: "http://test:8000" });

    await client.put("/items/1", { name: "updated" });

    const init = mockFetch.mock.calls[0]![1] as RequestInit;
    expect(init.method).toBe("PUT");
  });

  it("sends PATCH with JSON body", async () => {
    mockFetch.mockResolvedValue(jsonResponse({ patched: true }));
    const client = new SynClient({ baseUrl: "http://test:8000" });

    await client.patch("/items/1", { name: "patched" });

    const init = mockFetch.mock.calls[0]![1] as RequestInit;
    expect(init.method).toBe("PATCH");
  });

  it("sends DELETE", async () => {
    mockFetch.mockResolvedValue(jsonResponse({ deleted: true }));
    const client = new SynClient({ baseUrl: "http://test:8000" });

    await client.delete("/items/1");

    const init = mockFetch.mock.calls[0]![1] as RequestInit;
    expect(init.method).toBe("DELETE");
  });

  it("omits body when not provided on POST", async () => {
    mockFetch.mockResolvedValue(jsonResponse({}));
    const client = new SynClient({ baseUrl: "http://test:8000" });

    await client.post("/trigger");

    const init = mockFetch.mock.calls[0]![1] as RequestInit;
    expect(init.body).toBeUndefined();
  });
});
