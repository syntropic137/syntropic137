import { describe, expect, it } from "vitest";
import { parseSkillEntry, pinBundledRef } from "../../src/packages/skill-ref.js";

describe("parseSkillEntry", () => {
  it("parses org/repo/skill@version", () => {
    expect(parseSkillEntry("anthropics/skills/frontend-design@v1.2.0")).toEqual([
      {
        kind: "external",
        skillName: "frontend-design",
        sourceUrl: "https://github.com/anthropics/skills",
        version: "v1.2.0",
      },
    ]);
  });

  it("parses a full URL with @version", () => {
    expect(parseSkillEntry("https://github.com/acme/tdd-skill@v2.0.0")).toEqual([
      {
        kind: "external",
        skillName: "tdd-skill",
        sourceUrl: "https://github.com/acme/tdd-skill",
        version: "v2.0.0",
      },
    ]);
  });

  it("parses a bundled relative path, which carries no version yet", () => {
    expect(parseSkillEntry("./skills/repo-conventions")).toEqual([
      {
        kind: "bundled",
        skillName: "repo-conventions",
        localPath: "./skills/repo-conventions",
      },
    ]);
  });

  it("expands the verbose names[] form into one ref each", () => {
    const refs = parseSkillEntry({
      source: "github.com/acme/skills",
      version: "v1.0.0",
      names: ["alpha", "beta"],
    });
    expect(refs.map((r) => r.skillName)).toEqual(["alpha", "beta"]);
    expect(refs[0]!.kind).toBe("external");
  });

  it("rejects @latest because an unpinned ref cannot be cached", () => {
    expect(() => parseSkillEntry("anthropics/skills/foo@latest")).toThrow(/latest/i);
  });

  it("rejects the plugin-era two-segment shape with a corrective message", () => {
    expect(() => parseSkillEntry("acme/skills@v1.0.0")).toThrow(/org\/repo\/skill/);
  });

  it("rejects an unpinned external ref", () => {
    expect(() => parseSkillEntry("anthropics/skills/foo")).toThrow(/@version/);
  });
});

describe("pinBundledRef", () => {
  const tree = [
    { rel_path: "SKILL.md", content_base64: Buffer.from("# hi").toString("base64") },
  ];

  it("pins a bundled ref to its content hash, so identity tracks content", () => {
    const pinned = pinBundledRef(
      { kind: "bundled", skillName: "repo-conventions", localPath: "./skills/repo-conventions" },
      tree,
    );

    expect(pinned.kind).toBe("external");
    expect(pinned.skillName).toBe("repo-conventions");
    expect(pinned.sourceUrl).toBe("./skills/repo-conventions");
    expect(pinned.version).toMatch(/^sha256-[0-9a-f]{64}$/);
  });

  it("gives an edited skill a different identity", () => {
    const before = pinBundledRef(
      { kind: "bundled", skillName: "x", localPath: "./skills/x" },
      tree,
    );
    const after = pinBundledRef({ kind: "bundled", skillName: "x", localPath: "./skills/x" }, [
      { rel_path: "SKILL.md", content_base64: Buffer.from("# edited").toString("base64") },
    ]);

    // WHY this matters: RegisterSkillHandler returns an existing aggregate
    // before hashing the submitted files, so a fixed version literal would
    // silently keep serving the previously stored tree.
    expect(before.version).not.toBe(after.version);
  });

  it("hashes independently of the order files are listed in", () => {
    const a = pinBundledRef({ kind: "bundled", skillName: "x", localPath: "./skills/x" }, [
      { rel_path: "SKILL.md", content_base64: Buffer.from("# hi").toString("base64") },
      { rel_path: "refs/b.md", content_base64: Buffer.from("b").toString("base64") },
    ]);
    const b = pinBundledRef({ kind: "bundled", skillName: "x", localPath: "./skills/x" }, [
      { rel_path: "refs/b.md", content_base64: Buffer.from("b").toString("base64") },
      { rel_path: "SKILL.md", content_base64: Buffer.from("# hi").toString("base64") },
    ]);

    expect(a.version).toBe(b.version);
  });

  it("computes the same sha the server computes over the same tree", () => {
    // The server hashes sorted (rel_path, content) pairs, each NUL-terminated
    // (RegisterSkillHandler._compute_tree_sha). This value was produced by
    // that Python algorithm over [("SKILL.md", b"# hi")], and the same
    // constant is asserted from the Python side in
    // apps/syn-api/tests/test_skills_install_roundtrip.py. If the two
    // implementations ever drift, the version we register under stops
    // describing the content it names, and every install re-uploads.
    const pinned = pinBundledRef(
      { kind: "bundled", skillName: "x", localPath: "./skills/x" },
      tree,
    );

    expect(pinned.version).toBe(
      "sha256-1bba9894d50ccaf28bd7e2ace4e4103ffc6667734088ffb87796efd74df15b04",
    );
  });
});
