import { describe, it, expect } from "vitest";
import { parseYaml, YamlParseError } from "../../src/packages/yaml.js";

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
    const yaml = "prompt: |\n  Line one\n  Line two\n  Line three\nnext: 1\n";
    const result = parseYaml(yaml) as Record<string, unknown>;
    expect(result["prompt"]).toBe("Line one\nLine two\nLine three\n");
  });

  it("parses multiline folded string (>)", () => {
    const yaml = "desc: >\n  This is a\n  long description\nnext: 1\n";
    const result = parseYaml(yaml) as Record<string, unknown>;
    expect(result["desc"]).toBe("This is a long description\n");
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

  // #1618: the subset parser this replaced turned this into garbage silently.
  it("resolves anchors, aliases and merge keys, with local keys overriding", () => {
    const yaml = [
      "phases:",
      "  - &round",
      "    id: fix",
      "    model: opus",
      "    prompt_file: fix.md",
      "  - <<: *round",
      "    id: fix_2",
      "tools: &t [Read]",
      "again: *t",
      "",
    ].join("\n");
    expect(parseYaml(yaml)).toEqual({
      phases: [
        { id: "fix", model: "opus", prompt_file: "fix.md" },
        { id: "fix_2", model: "opus", prompt_file: "fix.md" },
      ],
      tools: ["Read"],
      again: ["Read"],
    });
  });

  // Same dialect as the server's PyYAML safe_load.
  it("reads YAML 1.1 booleans the way PyYAML does", () => {
    expect(parseYaml("a: yes\nb: off\n")).toEqual({ a: true, b: false });
  });

  it("fails with source and line on an undefined alias", () => {
    expect(() => parseYaml("a: 1\nb: *missing\n", "wf/workflow.yaml")).toThrow(
      /^wf\/workflow\.yaml:2: /,
    );
  });

  it("fails on a duplicate key instead of keeping one", () => {
    expect(() => parseYaml("id: a\nid: b\n", "x.yaml")).toThrow(YamlParseError);
  });

  it("fails with source and line on a value that has no JSON form", () => {
    expect(() => parseYaml("id: a\nwhen: 2026-10-05\n", "x.yaml")).toThrow(
      /^x\.yaml:2: a YAML Date has no JSON form/,
    );
    expect(() => parseYaml("b: !!binary aGk=\n", "x.yaml")).toThrow(/^x\.yaml:1: a YAML (Buffer|Uint8Array) has no JSON form/);
  });

  it("fails with source and line on a cyclic alias instead of overflowing", () => {
    expect(() => parseYaml("x: 1\na: &a {b: *a}\n", "x.yaml")).toThrow(
      /^x\.yaml:2: alias \*a is inside the node it refers to/,
    );
    expect(() => parseYaml("a: &a\n  k: 1\n  <<: *a\n", "x.yaml")).toThrow(/^x\.yaml:3: alias \*a/);
  });

  it("fails on more than one document", () => {
    expect(() => parseYaml("a: 1\n---\nb: 2\n", "x.yaml")).toThrow(/^x\.yaml:\d+: /);
  });
});
