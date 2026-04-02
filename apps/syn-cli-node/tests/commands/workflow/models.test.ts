import { describe, it, expect } from "vitest";
import { parseInputs } from "../../../src/commands/workflow/models.js";

describe("parseInputs", () => {
  it("returns empty object for undefined", () => {
    expect(parseInputs(undefined)).toEqual({});
  });

  it("returns empty object for empty array", () => {
    expect(parseInputs([])).toEqual({});
  });

  it("parses key=value pairs", () => {
    expect(parseInputs(["name=test", "count=42"])).toEqual({
      name: "test",
      count: 42,
    });
  });

  it("coerces booleans", () => {
    expect(parseInputs(["flag=true", "other=false"])).toEqual({
      flag: true,
      other: false,
    });
  });

  it("coerces integers", () => {
    expect(parseInputs(["count=42", "neg=-7"])).toEqual({ count: 42, neg: -7 });
  });

  it("coerces floats", () => {
    expect(parseInputs(["rate=3.14"])).toEqual({ rate: 3.14 });
  });

  it("preserves quoted strings without coercion", () => {
    expect(parseInputs(['num="42"'])).toEqual({ num: "42" });
  });

  it("handles values with equals signs", () => {
    expect(parseInputs(["query=a=b"])).toEqual({ query: "a=b" });
  });

  it("warns and skips invalid entries", () => {
    const stderr: string[] = [];
    const orig = process.stderr.write.bind(process.stderr);
    process.stderr.write = ((chunk: string) => {
      stderr.push(chunk);
      return true;
    }) as typeof process.stderr.write;

    const result = parseInputs(["noequalssign"]);

    process.stderr.write = orig;
    expect(result).toEqual({});
    expect(stderr.join("")).toContain("Warning");
  });
});
