import { describe, expect, it, beforeEach, afterEach } from "vitest";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { readSkillTree } from "../../src/packages/skill-tree.js";

let dir: string;

beforeEach(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), "skilltree-"));
});
afterEach(() => {
  fs.rmSync(dir, { recursive: true, force: true });
});

describe("readSkillTree", () => {
  it("reads SKILL.md and nested files with paths relative to the root", () => {
    fs.writeFileSync(path.join(dir, "SKILL.md"), "# hi");
    fs.mkdirSync(path.join(dir, "refs"));
    fs.writeFileSync(path.join(dir, "refs", "extra.md"), "more");

    const files = readSkillTree(dir);
    const byPath = Object.fromEntries(files.map((f) => [f.rel_path, f.content_base64]));

    expect(Object.keys(byPath).sort()).toEqual(["SKILL.md", "refs/extra.md"]);
    expect(Buffer.from(byPath["SKILL.md"]!, "base64").toString()).toBe("# hi");
  });

  it("throws when SKILL.md is missing, because that file IS the manifest", () => {
    fs.writeFileSync(path.join(dir, "notes.md"), "x");
    expect(() => readSkillTree(dir)).toThrow(/SKILL\.md/);
  });

  it("skips .git so a cloned skill does not upload its history", () => {
    fs.writeFileSync(path.join(dir, "SKILL.md"), "# hi");
    fs.mkdirSync(path.join(dir, ".git"));
    fs.writeFileSync(path.join(dir, ".git", "config"), "secret");

    expect(readSkillTree(dir).map((f) => f.rel_path)).toEqual(["SKILL.md"]);
  });
});
