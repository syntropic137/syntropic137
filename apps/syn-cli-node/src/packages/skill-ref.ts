import * as crypto from "node:crypto";

import type { SkillFilePayload } from "./skill-tree.js";

/**
 * A skill declared in workflow YAML, after parsing one `skills:` entry.
 *
 * The two kinds are distinguished in the type rather than by a sentinel
 * version string, because a bundled skill has NO version until its file tree
 * has been read and hashed. Making that a separate shape means a bundled ref
 * cannot reach registration without being pinned first (see `pinBundledRef`).
 */
export type ParsedSkillRef = ExternalSkillRef | BundledSkillRef;

/** A pinned reference to a skill hosted in some external repository. */
export interface ExternalSkillRef {
  readonly kind: "external";
  readonly skillName: string;
  readonly sourceUrl: string;
  readonly version: string;
}

/** A skill shipped inside the plugin, at a path relative to the plugin root. */
export interface BundledSkillRef {
  readonly kind: "bundled";
  readonly skillName: string;
  readonly localPath: string;
}

function rejectLatest(version: string): void {
  if (version.toLowerCase() === "latest") {
    throw new Error(
      "skill version '@latest' is not allowed: an unpinned ref cannot be cached, " +
        "because the same ref may denote different bytes later. Pin a tag or commit.",
    );
  }
}

function parseBundled(entry: string): ParsedSkillRef[] {
  const clean = entry.replace(/\/+$/, "");
  const skillName = clean.split("/").pop() ?? "";
  if (!skillName || skillName === "." || skillName === "..") {
    throw new Error(`bundled skill path has no directory name: ${entry}`);
  }
  return [{ kind: "bundled", skillName, localPath: clean }];
}

function parseStringRef(entry: string): ParsedSkillRef[] {
  if (entry.startsWith("./") || entry.startsWith("../")) return parseBundled(entry);

  const at = entry.lastIndexOf("@");
  if (at <= 0) {
    throw new Error(
      `skill ref must be pinned with @version: ${entry} ` +
        `(expected org/repo/skill@version or <url>@version)`,
    );
  }
  const body = entry.slice(0, at);
  const version = entry.slice(at + 1);
  rejectLatest(version);

  if (body.startsWith("http://") || body.startsWith("https://")) {
    const skillName = body.replace(/\/+$/, "").split("/").pop() ?? "";
    return [{ kind: "external", skillName, sourceUrl: body, version }];
  }

  const parts = body.split("/").filter(Boolean);
  if (parts.length !== 3) {
    throw new Error(
      `skill ref must be org/repo/skill@version, got '${entry}'. ` +
        `Two segments (org/repo@version) is the claude-plugin shape, not a skill ref.`,
    );
  }
  const [org, repo, skillName] = parts;
  return [
    {
      kind: "external",
      skillName: skillName!,
      sourceUrl: `https://github.com/${org}/${repo}`,
      version,
    },
  ];
}

function parseVerbose(entry: Record<string, unknown>): ParsedSkillRef[] {
  const source = entry["source"] ?? entry["source_url"];
  const version = entry["version"];
  if (typeof source !== "string" || typeof version !== "string") {
    throw new Error("skill verbose form requires string 'source' and 'version'");
  }
  rejectLatest(version);

  const sourceUrl = source.startsWith("http") ? source : `https://${source}`;
  const names = entry["names"];
  if (Array.isArray(names)) {
    if (names.length === 0) {
      throw new Error("skill verbose form 'names' must be a non-empty list of strings");
    }
    return names.map((n) => ({
      kind: "external" as const,
      skillName: String(n),
      sourceUrl,
      version,
    }));
  }
  const name = entry["name"];
  if (typeof name !== "string" || !name) {
    throw new Error("skill verbose form requires 'name' or a non-empty 'names' list");
  }
  return [{ kind: "external", skillName: name, sourceUrl, version }];
}

/** Expand one `skills:` YAML entry into one or more refs. */
export function parseSkillEntry(entry: unknown): ParsedSkillRef[] {
  if (typeof entry === "string") return parseStringRef(entry);
  if (typeof entry === "object" && entry !== null && !Array.isArray(entry)) {
    return parseVerbose(entry as Record<string, unknown>);
  }
  throw new Error(`unsupported skills: entry (expected string or mapping): ${String(entry)}`);
}

/**
 * SHA-256 over sorted (rel_path, content) pairs, each NUL-terminated.
 *
 * MUST match `RegisterSkillHandler._compute_tree_sha` byte for byte. Sorting
 * is what makes the hash independent of the order files were read in.
 */
export function hashSkillTree(files: readonly SkillFilePayload[]): string {
  const hasher = crypto.createHash("sha256");
  const sorted = [...files].sort((a, b) => (a.rel_path < b.rel_path ? -1 : a.rel_path > b.rel_path ? 1 : 0));
  for (const file of sorted) {
    hasher.update(Buffer.from(file.rel_path, "utf-8"));
    hasher.update(Buffer.from([0]));
    hasher.update(Buffer.from(file.content_base64, "base64"));
    hasher.update(Buffer.from([0]));
  }
  return hasher.digest("hex");
}

/**
 * Give a bundled skill a pinned, content-addressed identity.
 *
 * WHY the content hash and not the plugin version or a literal: registration
 * is keyed by (source_url, version, skill_name), and `RegisterSkillHandler`
 * returns an existing aggregate BEFORE hashing the submitted files. Under a
 * fixed version literal, editing a bundled skill would silently keep serving
 * the previously stored tree. With the hash in the version, an edit is simply
 * a different registration - which is exactly what it is.
 */
export function pinBundledRef(
  ref: BundledSkillRef,
  files: readonly SkillFilePayload[],
): ExternalSkillRef {
  return {
    kind: "external",
    skillName: ref.skillName,
    sourceUrl: ref.localPath,
    version: `sha256-${hashSkillTree(files)}`,
  };
}
