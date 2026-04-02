import { describe, it, expect } from "vitest";
import { parseYaml } from "../../src/packages/yaml.js";

describe("parseYaml", () => {
  it("parses simple key-value map", () => {
    const result = parseYaml("name: hello\nversion: 1");
    expect(result).toEqual({ name: "hello", version: 1 });
  });

  it("parses nested maps", () => {
    const result = parseYaml("repo:\n  url: https://example.com\n  ref: main");
    expect(result).toEqual({ repo: { url: "https://example.com", ref: "main" } });
  });

  it("parses lists", () => {
    const result = parseYaml("tags:\n  - alpha\n  - beta\n  - gamma");
    expect(result).toEqual({ tags: ["alpha", "beta", "gamma"] });
  });

  it("parses list of maps", () => {
    const yaml = "phases:\n  - id: discovery\n    name: Discovery\n  - id: deep-dive\n    name: Deep Dive";
    const result = parseYaml(yaml) as Record<string, unknown>;
    const phases = result["phases"] as Record<string, unknown>[];
    expect(phases).toHaveLength(2);
    expect(phases[0]).toEqual({ id: "discovery", name: "Discovery" });
    expect(phases[1]).toEqual({ id: "deep-dive", name: "Deep Dive" });
  });

  it("parses booleans and null", () => {
    const result = parseYaml("enabled: true\ndisabled: false\nempty: null");
    expect(result).toEqual({ enabled: true, disabled: false, empty: null });
  });

  it("parses quoted strings", () => {
    const result = parseYaml('name: "hello world"\ntype: \'custom\'');
    expect(result).toEqual({ name: "hello world", type: "custom" });
  });

  it("parses flow sequences", () => {
    const result = parseYaml("tools: [Read, Write, Bash]");
    expect(result).toEqual({ tools: ["Read", "Write", "Bash"] });
  });

  it("parses multiline literal string (|)", () => {
    const yaml = "prompt: |\n  Line one\n  Line two\n  Line three";
    const result = parseYaml(yaml) as Record<string, unknown>;
    expect(result["prompt"]).toBe("Line one\nLine two\nLine three");
  });

  it("parses multiline folded string (>)", () => {
    const yaml = "desc: >\n  This is a\n  long description";
    const result = parseYaml(yaml) as Record<string, unknown>;
    expect(result["desc"]).toBe("This is a long description");
  });

  it("skips comments", () => {
    const result = parseYaml("# A comment\nname: test # inline comment\ncount: 42");
    expect(result).toEqual({ name: "test", count: 42 });
  });

  it("parses numbers", () => {
    const result = parseYaml("int: 42\nfloat: 3.14\nneg: -7");
    expect(result).toEqual({ int: 42, float: 3.14, neg: -7 });
  });

  it("handles empty input", () => {
    expect(parseYaml("")).toBeNull();
    expect(parseYaml("# just a comment")).toBeNull();
  });
});
