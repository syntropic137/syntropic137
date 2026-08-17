import { describe, expect, it } from "vitest";
import { hashSkillTree, parseSkillEntry, pinBundledRef } from "../../src/packages/skill-ref.js";

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

describe("cross-language agreement with the Python domain parser", () => {
  // These forms are accepted by packages/syn-domain/.../_shared/skill_ref.py.
  // A form the CLI rejects fails the install outright; a form it parses to a
  // DIFFERENT identity is worse - it registers under one triple while
  // SkillResolutionService looks up another, so the run dies with
  // SkillNotRegistered after the user committed to it.

  it("strips a .git suffix when deriving the name, as _basename_from_url does", () => {
    expect(parseSkillEntry("https://github.com/acme/tdd-skill.git@v2.0.0")).toEqual([
      {
        kind: "external",
        skillName: "tdd-skill",
        sourceUrl: "https://github.com/acme/tdd-skill.git",
        version: "v2.0.0",
      },
    ]);
  });

  it("accepts ssh and git protocol URLs", () => {
    expect(parseSkillEntry("git@github.com:acme/tdd-skill@v1.0.0")[0]).toMatchObject({
      skillName: "tdd-skill",
      version: "v1.0.0",
    });
    expect(parseSkillEntry("ssh://git@github.com/acme/tdd-skill@v1.0.0")[0]).toMatchObject({
      skillName: "tdd-skill",
      version: "v1.0.0",
    });
  });

  it("expands bare-host shorthand to https in the verbose form", () => {
    expect(parseSkillEntry({ source: "github.com/acme/skills", version: "v1", name: "alpha" })).toEqual([
      {
        kind: "external",
        skillName: "alpha",
        sourceUrl: "https://github.com/acme/skills",
        version: "v1",
      },
    ]);
  });

  it("rejects a version containing a slash in the compact string form", () => {
    // Ambiguous: cannot tell a branch pin from part of the URL. The verbose
    // form has no such ambiguity and is where slash versions belong.
    expect(() => parseSkillEntry("https://github.com/acme/skill@feature/foo")).toThrow(/verbose/i);
  });

  it("rejects a non-string entry in names[]", () => {
    expect(() =>
      parseSkillEntry({ source: "github.com/a/b", version: "v1", names: ["ok", 3] }),
    ).toThrow(/names/i);
  });

  it("rejects a skill name that is not a single safe path segment", () => {
    // The name becomes a directory under .syn-skills/ and a path inside a
    // clone, so a separator or dot-segment here is a filesystem escape.
    expect(() =>
      parseSkillEntry({ source: "github.com/a/b", version: "v1", name: "../../etc" }),
    ).toThrow(/name/i);
  });
});

describe("hashSkillTree ordering", () => {
  it("orders paths by UTF-8 bytes, matching Python rather than UTF-16", () => {
    // JS string comparison orders by UTF-16 code unit, so U+10000 (a surrogate
    // pair starting 0xD800) sorts BEFORE U+E000. Python orders by code point,
    // which for UTF-8 is byte order, and puts U+E000 first. Sorting the raw
    // strings therefore produces a different digest per language for any tree
    // containing a non-BMP filename.
    const files = [
      { rel_path: "\u{10000}.md", content_base64: Buffer.from("a").toString("base64") },
      { rel_path: ".md", content_base64: Buffer.from("b").toString("base64") },
    ];

    // Value produced by RegisterSkillHandler._compute_tree_sha over the same tree.
    expect(hashSkillTree(files)).toBe(
      "bcf3e1770dfcf6ff19fa867bf3d613c8112aa1ba5347949eb875769bb86fa35c",
    );
  });
});
