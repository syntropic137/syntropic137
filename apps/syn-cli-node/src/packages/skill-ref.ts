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

// URL prefixes the domain treats as "this whole string is <url>@<version>".
// Kept in sync with _URL_PREFIXES in
// packages/syn-domain/.../_shared/skill_ref.py. An ssh form already contains an
// '@' before the version, which is why the version splits on the LAST one.
const URL_PREFIXES = ["http://", "https://", "git+ssh://", "ssh://", "git://", "git@"];

// Bare-host shorthand like "github.com/org/repo" expands to https://.
const BARE_HOST_RE = /^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\//;

/**
 * Last path segment of a URL, minus a `.git` suffix.
 *
 * WHY the `.git` strip matters: the domain's `_basename_from_url` does it, and
 * the derived name is part of the identity triple. Without it the CLI would
 * register `tdd-skill.git` while run-time resolution looks up `tdd-skill`, and
 * the run would fail with SkillNotRegistered after the user committed to it.
 */
function basenameFromUrl(url: string): string {
  let tail = url.replace(/\/+$/, "");
  for (const sep of ["/", ":"]) {
    const idx = tail.lastIndexOf(sep);
    if (idx >= 0) {
      tail = tail.slice(idx + 1);
      break;
    }
  }
  return tail.endsWith(".git") ? tail.slice(0, -".git".length) : tail;
}

/**
 * Reject a skill name that is not one safe path segment.
 *
 * The name becomes a directory under `.syn-skills/<name>/` in the workspace and
 * a lookup path inside a clone, so a separator, a dot-segment, or a control
 * character here is a filesystem escape rather than a naming mistake.
 */
function requireSafeSkillName(name: string): string {
  const trimmed = name.trim();
  const unsafe =
    !trimmed ||
    trimmed === "." ||
    trimmed === ".." ||
    trimmed.startsWith(".") ||
    trimmed.includes("/") ||
    trimmed.includes("\\") ||
    // eslint-disable-next-line no-control-regex
    /[\x00-\x1f\x7f]/.test(trimmed);
  if (unsafe) {
    throw new Error(
      `skill name ${JSON.stringify(name)} must be a single path segment: no separators, ` +
        `no '.' or '..', no leading dot, no control characters`,
    );
  }
  return trimmed;
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

  // WHY reject '..' anywhere rather than only checking the basename: the path
  // is joined onto the plugin root and the resulting directory is read and
  // uploaded. `./skills/../../secrets` has a perfectly good basename and still
  // escapes the plugin. Containment is re-proved against the resolved path in
  // the preflight; this rejects the obvious shape early, with a clear message.
  const segments = clean.split("/");
  if (segments.some((s) => s === "..")) {
    throw new Error(
      `bundled skill path '${entry}' must stay inside the plugin: '..' segments are not allowed`,
    );
  }
  const skillName = segments[segments.length - 1] ?? "";
  if (!skillName || skillName === ".") {
    throw new Error(`bundled skill path has no directory name: ${entry}`);
  }
  return [{ kind: "bundled", skillName: requireSafeSkillName(skillName), localPath: clean }];
}

/** Parse the `<url>@<version>` form, splitting on the LAST '@'. */
function parseUrlForm(entry: string): ParsedSkillRef[] {
  const at = entry.lastIndexOf("@");
  const body = entry.slice(0, at);
  const version = entry.slice(at + 1);

  if (!version) {
    throw new Error(`skill reference '${entry}' has empty version after '@'`);
  }
  if (version.includes("://")) {
    throw new Error(
      `skill reference '${entry}' is missing '@<version>' suffix; expected '<url>@<tag-or-sha>'`,
    );
  }
  if (version.includes("/")) {
    // Ambiguous in the compact form: we cannot tell a slash-bearing branch pin
    // from the rest of the URL. The verbose mapping has the two fields already
    // split, so it carries such versions without ambiguity.
    throw new Error(
      `skill reference '${entry}' has a '/' in the version segment, which is ambiguous ` +
        `in the '<url>@<version>' string form; use the verbose mapping form ` +
        `('source'/'version' keys) for versions containing '/'`,
    );
  }
  rejectLatest(version);

  // Any '@' left in the URL beyond the ssh user-info prefix came from the ref
  // name itself, and splitting on the last one would silently corrupt the pin.
  let remainder = body;
  for (const prefix of URL_PREFIXES) {
    if (remainder.startsWith(prefix)) {
      remainder = remainder.slice(prefix.length);
      break;
    }
  }
  if (remainder.startsWith("git@")) remainder = remainder.slice("git@".length);
  if (remainder.includes("@")) {
    throw new Error(
      `skill reference '${entry}' has an ambiguous '@' (the ref name itself contains '@'); ` +
        `use the verbose mapping form with separate source and version`,
    );
  }

  return [
    {
      kind: "external",
      skillName: requireSafeSkillName(basenameFromUrl(body)),
      sourceUrl: body,
      version,
    },
  ];
}

function parseStringRef(raw: string): ParsedSkillRef[] {
  const entry = raw.trim();
  if (!entry) throw new Error("skill reference cannot be empty");
  if (entry.startsWith("./") || entry.startsWith("../")) return parseBundled(entry);

  if (URL_PREFIXES.some((p) => entry.startsWith(p))) return parseUrlForm(entry);

  if (BARE_HOST_RE.test(entry)) {
    throw new Error(
      `skill reference '${entry}' looks like a host-qualified path; use the full URL form ` +
        `'<url>@<version>' or the verbose mapping form`,
    );
  }

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
      skillName: requireSafeSkillName(skillName!),
      sourceUrl: `https://github.com/${org}/${repo}`,
      version,
    },
  ];
}

/** Bare-host shorthand expands to https; a recognized protocol passes through. */
function normalizeSource(source: string): string {
  const trimmed = source.trim();
  if (URL_PREFIXES.some((p) => trimmed.startsWith(p))) return trimmed;
  return BARE_HOST_RE.test(trimmed) ? `https://${trimmed}` : trimmed;
}

/** Expand `names: [a, b]` into one ref per name, sharing source and version. */
function refsFromNames(names: readonly unknown[], sourceUrl: string, version: string): ParsedSkillRef[] {
  if (names.length === 0) {
    throw new Error("skill verbose form 'names' must be a non-empty list of strings");
  }
  return names.map((n) => {
    if (typeof n !== "string") {
      throw new Error(
        `skill verbose form 'names' must contain only strings, got ${JSON.stringify(n)}`,
      );
    }
    return {
      kind: "external" as const,
      skillName: requireSafeSkillName(n),
      sourceUrl,
      version,
    };
  });
}

function parseVerbose(entry: Record<string, unknown>): ParsedSkillRef[] {
  const source = entry["source"] ?? entry["source_url"];
  const version = entry["version"];
  if (typeof source !== "string" || typeof version !== "string") {
    throw new Error("skill verbose form requires string 'source' and 'version'");
  }
  rejectLatest(version);

  const sourceUrl = normalizeSource(source);
  const pinned = version.trim();

  const names = entry["names"];
  if (Array.isArray(names)) return refsFromNames(names, sourceUrl, pinned);

  const name = entry["name"];
  if (name !== undefined && typeof name !== "string") {
    throw new Error(`skill verbose form 'name' must be a string, got ${JSON.stringify(name)}`);
  }
  const effectiveName = typeof name === "string" && name.trim() ? name : basenameFromUrl(sourceUrl);
  return [
    {
      kind: "external",
      skillName: requireSafeSkillName(effectiveName),
      sourceUrl,
      version: pinned,
    },
  ];
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
 *
 * WHY sort by UTF-8 bytes and not by the strings themselves: JavaScript orders
 * strings by UTF-16 code unit, so a non-BMP path (a surrogate pair starting
 * 0xD800) sorts before U+E000; Python orders by code point, which for UTF-8 is
 * byte order, and puts U+E000 first. Comparing raw strings therefore yields a
 * different digest per language for any tree containing a non-BMP filename,
 * which would silently break both the cache and run-time resolution. Python
 * already matches byte order, so this is a one-sided fix with no rehashing.
 */
export function hashSkillTree(files: readonly SkillFilePayload[]): string {
  const hasher = crypto.createHash("sha256");
  const sorted = [...files].sort((a, b) =>
    Buffer.compare(Buffer.from(a.rel_path, "utf-8"), Buffer.from(b.rel_path, "utf-8")),
  );
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
