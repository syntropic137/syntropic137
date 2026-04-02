import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiGet, apiGetList, apiPost, buildParams } from "../../src/client/api.js";
import { CLIError } from "../../src/framework/errors.js";

describe("api helpers", () => {
  const mockFetch = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("fetch", mockFetch);
    vi.spyOn(process.stderr, "write").mockReturnValue(true);
    vi.spyOn(process.stdout, "write").mockReturnValue(true);
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

  describe("apiGet", () => {
    it("returns data on success", async () => {
      mockFetch.mockResolvedValue(jsonResponse({ status: "ok" }));
      const result = await apiGet<{ status: string }>("/health");
      expect(result.status).toBe("ok");
    });

    it("throws CLIError on non-200 status with detail message", async () => {
      mockFetch.mockResolvedValue(
        jsonResponse({ detail: "Not Found" }, 404),
      );
      await expect(apiGet("/missing")).rejects.toThrow("Not Found");
    });

    it("throws CLIError with HTTP status when no detail", async () => {
      mockFetch.mockResolvedValue(jsonResponse({}, 500));
      await expect(apiGet("/fail")).rejects.toThrow("HTTP 500");
    });

    it("throws CLIError on network error", async () => {
      mockFetch.mockRejectedValue(new TypeError("fetch failed"));
      await expect(apiGet("/health")).rejects.toThrow(CLIError);
    });
  });

  describe("apiGetList", () => {
    it("returns array data", async () => {
      mockFetch.mockResolvedValue(jsonResponse([{ id: 1 }, { id: 2 }]));
      const result = await apiGetList<{ id: number }>("/items");
      expect(result).toHaveLength(2);
    });
  });

  describe("apiPost", () => {
    it("sends body and returns data", async () => {
      mockFetch.mockResolvedValue(jsonResponse({ id: "abc" }));
      const result = await apiPost<{ id: string }>("/items", {
        body: { name: "test" },
      });
      expect(result.id).toBe("abc");
    });
  });

  describe("buildParams", () => {
    it("filters null and undefined", () => {
      const result = buildParams({
        a: "1",
        b: null,
        c: undefined,
        d: 42,
        e: true,
      });
      expect(result).toEqual({ a: "1", d: "42", e: "true" });
    });
  });
});
