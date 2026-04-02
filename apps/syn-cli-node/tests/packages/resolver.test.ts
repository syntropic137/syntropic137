import { describe, it, expect } from "vitest";
import { parseSource } from "../../src/packages/resolver.js";

describe("parseSource", () => {
  it("detects HTTPS URLs as remote", () => {
    const result = parseSource("https://github.com/org/repo.git");
    expect(result).toEqual({ resolved: "https://github.com/org/repo.git", isRemote: true });
  });

  it("detects SSH URLs as remote", () => {
    const result = parseSource("git@github.com:org/repo.git");
    expect(result).toEqual({ resolved: "git@github.com:org/repo.git", isRemote: true });
  });

  it("detects GitHub shorthand as remote", () => {
    const result = parseSource("syntropic137/workflow-library");
    expect(result).toEqual({
      resolved: "https://github.com/syntropic137/workflow-library.git",
      isRemote: true,
    });
  });

  it("detects relative paths as local", () => {
    const result = parseSource("./my-package");
    expect(result).toEqual({ resolved: "./my-package", isRemote: false });
  });

  it("detects absolute paths as local", () => {
    const result = parseSource("/tmp/my-package");
    expect(result).toEqual({ resolved: "/tmp/my-package", isRemote: false });
  });

  it("treats bare names as local", () => {
    const result = parseSource("my-workflow");
    expect(result).toEqual({ resolved: "my-workflow", isRemote: false });
  });
});
