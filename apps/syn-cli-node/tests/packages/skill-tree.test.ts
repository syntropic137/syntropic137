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

describe("readSkillTree limits", () => {
  it("refuses a tree with more files than the API would accept", () => {
    // Enforced during traversal, not after: the API's cap only applies once a
    // request arrives, so without this a plugin could exhaust CLI memory
    // before the server ever saw it.
    fs.writeFileSync(path.join(dir, "SKILL.md"), "# hi");
    const many = path.join(dir, "many");
    fs.mkdirSync(many);
    for (let i = 0; i < 10_001; i++) {
      fs.writeFileSync(path.join(many, `f${i}.md`), "x");
    }

    expect(() => readSkillTree(dir)).toThrow(/10000|10,000|files/i);
  });

  it("refuses a tree larger than the API byte cap without reading the big file", () => {
    fs.writeFileSync(path.join(dir, "SKILL.md"), "# hi");
    // Sparse file: 60 MiB of length, negligible disk. Reading it would cost
    // 60 MiB of RSS, which is exactly what the pre-read size check avoids.
    const fd = fs.openSync(path.join(dir, "big.bin"), "w");
    fs.ftruncateSync(fd, 60 * 1024 * 1024);
    fs.closeSync(fd);

    expect(() => readSkillTree(dir)).toThrow(/bytes|MiB/i);
  });

  it("skips a symlink rather than following it out of the tree", () => {
    fs.writeFileSync(path.join(dir, "SKILL.md"), "# hi");
    const secret = path.join(os.tmpdir(), `secret-${process.pid}.txt`);
    fs.writeFileSync(secret, "do not upload me");
    fs.symlinkSync(secret, path.join(dir, "link.txt"));

    expect(readSkillTree(dir).map((f) => f.rel_path)).toEqual(["SKILL.md"]);

    fs.rmSync(secret, { force: true });
  });
});
