import * as fs from "node:fs";
import * as path from "node:path";

/** One file in a skill tree, shaped for RegisterSkillRequest.files[]. */
export interface SkillFilePayload {
  readonly rel_path: string;
  readonly content_base64: string;
}

const SKIP_DIRS = new Set([".git", "node_modules", "__pycache__"]);
const MANIFEST = "SKILL.md";

// Mirrors MAX_SKILL_TREE_FILES / MAX_SKILL_TREE_BYTES in
// apps/syn-api/src/syn_api/routes/skills.py. Enforced here DURING traversal,
// not after: the API's limits only apply once a request arrives, so a
// marketplace plugin with a huge tree would otherwise exhaust CLI memory while
// being read, encoded, and serialized, long before the server could refuse it.
const MAX_FILES = 10_000;
const MAX_BYTES = 50 * 1024 * 1024;

interface WalkBudget {
  files: number;
  bytes: number;
}

function checkBudget(budget: WalkBudget, dir: string): void {
  if (budget.files > MAX_FILES) {
    throw new Error(`skill directory ${dir} has more than ${MAX_FILES} files; refusing to read it`);
  }
  if (budget.bytes > MAX_BYTES) {
    throw new Error(
      `skill directory ${dir} exceeds ${MAX_BYTES} bytes ` +
        `(${MAX_BYTES / (1024 * 1024)} MiB); refusing to read it`,
    );
  }
}

function walk(root: string, dir: string, out: SkillFilePayload[], budget: WalkBudget): void {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (SKIP_DIRS.has(entry.name)) continue;
    const abs = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      walk(root, abs, out, budget);
      continue;
    }
    // isFile() is false for symlinks, so a link pointing outside the tree is
    // skipped rather than followed and uploaded.
    if (!entry.isFile()) continue;

    // Size is taken from the directory entry BEFORE reading, so the file that
    // crosses the limit is never loaded into memory.
    budget.files += 1;
    budget.bytes += fs.statSync(abs).size;
    checkBudget(budget, root);

    out.push({
      rel_path: path.relative(root, abs).split(path.sep).join("/"),
      content_base64: fs.readFileSync(abs).toString("base64"),
    });
  }
}

/**
 * Read every file in a skill directory, base64-encoded, paths relative to the root.
 *
 * SKILL.md at the root is required: unlike claude plugins there is no
 * caller-supplied manifest, so its frontmatter IS the manifest.
 */
export function readSkillTree(dir: string): SkillFilePayload[] {
  if (!fs.existsSync(path.join(dir, MANIFEST))) {
    throw new Error(`skill directory ${dir} has no ${MANIFEST} at its root`);
  }
  const out: SkillFilePayload[] = [];
  walk(dir, dir, out, { files: 0, bytes: 0 });
  return out;
}

/**
 * Locate the skill directory inside a freshly cloned repository.
 *
 * A skills repo usually publishes many skills as subdirectories, but a
 * single-skill repo puts SKILL.md at its root. Candidates are tried in
 * most-specific-first order so a repo containing both a `<name>/` directory
 * and a root SKILL.md resolves to the named one.
 *
 * The skill name is already validated as a single safe path segment by
 * `requireSafeSkillName`, so it cannot escape the clone directory here.
 */
export function skillDirInClone(cloneDir: string, skillName: string): string {
  const candidates = [
    path.join(cloneDir, skillName),
    path.join(cloneDir, "skills", skillName),
    cloneDir,
  ];
  for (const candidate of candidates) {
    try {
      readSkillTree(candidate);
      return candidate;
    } catch {
      continue;
    }
  }
  throw new Error(
    `cloned source has no skill '${skillName}' (looked for a SKILL.md in ` +
      `${skillName}/, skills/${skillName}/, and the repository root)`,
  );
}
