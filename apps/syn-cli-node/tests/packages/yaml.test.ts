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
  // -------------------------------------------------------------------------
  // Fail closed on unsupported constructs (#1056)
  // -------------------------------------------------------------------------
  //
  // The parser used to stop at the first line it could not place and return
  // whatever it had so far. Every one of these documents previously parsed
  // "successfully" while silently losing data.
  describe("fail closed", () => {
    it("refuses a quoted scalar that wraps, instead of dropping the keys after it", () => {
      const yaml = [
        "id: wrapped",
        "description: 'One line description that wraps across two physical lines because",
        "  the emitter folded it at eighty columns.'",
        "type: sdlc",
        "phases:",
        "  - id: alpha",
      ].join("\n");

      // Previously returned { id, description } — `type` and `phases` gone.
      // Reported against line 2, where the quote opens, not the continuation.
      expect(() => parseYaml(yaml)).toThrow(/YAML line 2/);
    });

    it("refuses an unclosed quote even when nothing follows it", () => {
      // No leftover lines here, so only the quote check can catch this one.
      // Previously returned { id: "x", description: "'oops" } — the dangling
      // quote kept as data.
      expect(() => parseYaml("id: x\ndescription: 'oops")).toThrow(/line 2/);
    });

    it("refuses a block scalar with a chomping indicator rather than dropping the rest", () => {
      // `>-` and `|-` are not in the supported subset: only bare `>` and `|`
      // are matched. This shape is what PyYAML emits for folded strings, and
      // it previously truncated the document at the block.
      const yaml = ["name: skill", "description: >-", "  folded body text", "version: 2"].join("\n");

      expect(() => parseYaml(yaml)).toThrow(/line 3/);
    });

    it("refuses trailing content the parser could not place", () => {
      // No quote anywhere: this isolates the leftover-content guard from the
      // unclosed-quote one. The indented line belongs to no open container,
      // so the document used to end silently at `a` and return { a: 1 }.
      expect(() => parseYaml("a: 1\n  stray: 2")).toThrow(
        /YAML line 2: unsupported construct/,
      );
    });

    it("still accepts a document it fully understands", () => {
      // The guard must not fire on the supported subset. Trailing blank lines
      // and comments after the last key are not leftover content.
      const yaml = "id: fine\nphases:\n  - id: alpha\n\n# trailing comment\n";
      expect(parseYaml(yaml)).toEqual({ id: "fine", phases: [{ id: "alpha" }] });
    });
  });
});
