import { describe, it, expect } from "vitest";
import { validateRegistryName, isCacheStale } from "../../src/marketplace/client.js";
import { MarketplaceIndexSchema } from "../../src/marketplace/models.js";

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

// WHY (#763): the schema must accept a marketplace.json without the
// `syntropic137` marker so claude-plugin marketplaces (e.g.
// AgentParadise/agentic-primitives) can be parsed.
describe("MarketplaceIndexSchema (#763 claude-plugin compat)", () => {
  it("accepts a marketplace.json without the syntropic137 marker", () => {
    const parsed = MarketplaceIndexSchema.parse({
      name: "agentic-primitives",
      plugins: [
        { name: "sdlc", source: "./plugins/sdlc", category: "dev" },
        { name: "research", source: "./plugins/research", category: "dev" },
      ],
    });
    expect(parsed.plugins).toHaveLength(2);
    expect(parsed.syntropic137).toBeUndefined();
    expect(parsed.plugins[0]!.name).toBe("sdlc");
  });

  it("preserves the marker when present (workflow marketplaces)", () => {
    const parsed = MarketplaceIndexSchema.parse({
      name: "wf",
      syntropic137: { type: "workflow-marketplace" },
      plugins: [],
    });
    expect(parsed.syntropic137?.type).toBe("workflow-marketplace");
  });
});
