import * as fs from "node:fs";
import * as path from "node:path";

/** One file in a skill tree, shaped for RegisterSkillRequest.files[]. */
export interface SkillFilePayload {
  readonly rel_path: string;
  readonly content_base64: string;
}

const SKIP_DIRS = new Set([".git", "node_modules", "__pycache__"]);
const MANIFEST = "SKILL.md";

function walk(root: string, dir: string, out: SkillFilePayload[]): void {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (SKIP_DIRS.has(entry.name)) continue;
    const abs = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      walk(root, abs, out);
      continue;
    }
    if (!entry.isFile()) continue;
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
  walk(dir, dir, out);
  return out;
}
