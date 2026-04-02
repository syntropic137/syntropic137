import { describe, it, expect } from "vitest";
import { validateRegistryName, isCacheStale } from "../../src/marketplace/client.js";

describe("validateRegistryName", () => {
  it("accepts valid names", () => {
    expect(validateRegistryName("my-registry")).toBe("my-registry");
    expect(validateRegistryName("registry_1")).toBe("registry_1");
    expect(validateRegistryName("Registry.v2")).toBe("Registry.v2");
  });

  it("rejects names starting with non-alphanumeric", () => {
    expect(() => validateRegistryName("-bad")).toThrow("Invalid registry name");
    expect(() => validateRegistryName(".bad")).toThrow("Invalid registry name");
    expect(() => validateRegistryName("_bad")).toThrow("Invalid registry name");
  });

  it("rejects names with path traversal", () => {
    expect(() => validateRegistryName("a..b")).toThrow("Invalid registry name");
  });

  it("rejects names with special chars", () => {
    expect(() => validateRegistryName("a/b")).toThrow("Invalid registry name");
    expect(() => validateRegistryName("a b")).toThrow("Invalid registry name");
  });
});

describe("isCacheStale", () => {
  it("returns false for recent cache", () => {
    const cached = {
      fetched_at: new Date().toISOString(),
      index: { name: "test", syntropic137: { type: "workflow-marketplace" as const }, plugins: [] },
    };
    expect(isCacheStale(cached)).toBe(false);
  });

  it("returns true for old cache", () => {
    const old = new Date(Date.now() - 5 * 60 * 60 * 1000).toISOString();
    const cached = {
      fetched_at: old,
      index: { name: "test", syntropic137: { type: "workflow-marketplace" as const }, plugins: [] },
    };
    expect(isCacheStale(cached)).toBe(true);
  });

  it("returns true for invalid date", () => {
    const cached = {
      fetched_at: "not-a-date",
      index: { name: "test", syntropic137: { type: "workflow-marketplace" as const }, plugins: [] },
    };
    expect(isCacheStale(cached)).toBe(true);
  });
});
