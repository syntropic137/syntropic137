// See ADR-066: git work and tree-walking happen in this CLI tier per the
// thin-API rule. The API never spawns subprocesses or reads the user's
// filesystem; the CLI does the local work and POSTs structured payloads.
/**
 * Shared helpers for `syn claude-plugin` commands.
 *
 * - parseClaudePluginRef: parses the same string forms as the Python
 *   ClaudePluginRef in
 *   packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/claude_plugin_ref.py.
 *   The two parsers MUST stay in sync; if you add a form here, mirror it
 *   there (and vice versa).
 * - walkPluginTree: recursive fs walk producing the inline file payload the
 *   API expects (rel_path + base64). Skips .git, hidden files in repo root,
 *   and refuses oversized trees up-front so we never PUT 500MB to the API.
 * - readPluginManifest: reads .claude-plugin/plugin.json and validates it has
 *   a name field.
 */

import fs from "node:fs";
import path from "node:path";
import { CLIError } from "../framework/errors.js";

/** Hard cap on the total uncompressed tree size we will upload (50 MiB). */
export const MAX_TREE_BYTES = 50 * 1024 * 1024;

export interface ParsedClaudePluginRef {
  /** Display name derived from the ref (org/repo -> repo, url -> basename). */
  readonly name: string;
  /** Canonical clone URL (https for github shorthand). */
  readonly source_url: string;
  /** Tag, branch, or sha. Never the literal string "latest". */
  readonly version: string;
  /**
   * True when the verbose mapping form supplied an explicit `name:` override.
   * The override is authoritative over the manifest name (mirrors the Python
   * ClaudePluginRef, whose lock key is (source_url, version, name)).
   */
  readonly name_overridden?: boolean;
}

export interface PluginFileEntry {
  readonly rel_path: string;
  readonly content_b64: string;
}

export interface PluginManifest {
  readonly name: string;
  readonly [key: string]: unknown;
}

const URL_PREFIXES = [
  "http://",
  "https://",
  "git+ssh://",
  "ssh://",
  "git://",
  "git@",
] as const;

const GITHUB_SHORTHAND_RE = /^([^/@\s]+)\/([^/@\s]+)@(.+)$/;
const BARE_HOST_RE = /^[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\//;

function basenameFromUrl(url: string): string {
  let tail = url.replace(/\/+$/, "");
  for (const sep of ["/", ":"]) {
    const idx = tail.lastIndexOf(sep);
    if (idx >= 0) {
      tail = tail.slice(idx + 1);
      break;
    }
  }
  if (tail.endsWith(".git")) tail = tail.slice(0, -4);
  return tail;
}

function startsWithUrlPrefix(raw: string): boolean {
  return URL_PREFIXES.some((p) => raw.startsWith(p));
}

function rejectLatest(version: string): void {
  if (version.trim().toLowerCase() === "latest") {
    throw new CLIError(
      "claude plugin version must be a specific tag/branch/sha; '@latest' is not allowed for reproducibility",
    );
  }
}

function tryParseGithubShorthand(trimmed: string): ParsedClaudePluginRef | null {
  // WHY: Form A only applies to bare "org/repo@version"; full URLs contain
  // "://" or "git@" and are handled by Form B.
  if (trimmed.includes("://") || trimmed.startsWith("git@")) return null;
  const match = GITHUB_SHORTHAND_RE.exec(trimmed);
  if (!match) return null;
  const [, org, repo, version] = match as unknown as [string, string, string, string];
  rejectLatest(version);
  return {
    name: repo,
    source_url: `https://github.com/${org}/${repo}`,
    version,
  };
}

function missingVersionError(raw: string): CLIError {
  return new CLIError(
    `claude plugin reference '${raw}' is missing '@<version>' suffix; expected '<url>@<tag-or-sha>'`,
  );
}

function parseUrlForm(trimmed: string, raw: string): ParsedClaudePluginRef {
  // WHY: split on the LAST @ because git@host: and git+ssh://git@host
  // already contain an @ before the version delimiter. "git@" is 4 chars;
  // reject if @ is part of the protocol prefix only.
  const lastAt = trimmed.lastIndexOf("@");
  if (lastAt < 4) throw missingVersionError(raw);
  const urlPart = trimmed.slice(0, lastAt);
  const version = trimmed.slice(lastAt + 1);
  if (version === "" || version.includes("://") || version.includes("/")) {
    throw missingVersionError(raw);
  }
  rejectLatest(version);
  return {
    name: basenameFromUrl(urlPart),
    source_url: urlPart,
    version,
  };
}

export function parseClaudePluginRef(raw: string): ParsedClaudePluginRef {
  const trimmed = raw.trim();
  if (trimmed === "") {
    throw new CLIError("claude plugin reference cannot be empty");
  }

  // Form A: github shorthand "org/repo@version".
  const shorthand = tryParseGithubShorthand(trimmed);
  if (shorthand !== null) return shorthand;

  // Form B: full URL with @version suffix.
  if (startsWithUrlPrefix(trimmed)) {
    return parseUrlForm(trimmed, raw);
  }

  // Form C: bare-host shorthand like "github.com/org/repo@v1" - normalize
  // to https:// and re-enter Form B logic.
  if (BARE_HOST_RE.test(trimmed)) {
    return parseClaudePluginRef(`https://${trimmed}`);
  }

  throw new CLIError(
    `claude plugin reference '${raw}' is not a recognized form; expected 'org/repo@version' or '<url>@<version>'`,
  );
}

/**
 * Read .claude-plugin/plugin.json from a cloned tree and validate.
 * Throws CLIError if the file is missing, malformed, or lacks a name.
 */
export function readPluginManifest(rootDir: string): PluginManifest {
  const manifestPath = path.join(rootDir, ".claude-plugin", "plugin.json");
  if (!fs.existsSync(manifestPath)) {
    throw new CLIError(
      "not a valid claude plugin: missing .claude-plugin/plugin.json",
    );
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(fs.readFileSync(manifestPath, "utf-8"));
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err);
    throw new CLIError(`.claude-plugin/plugin.json is not valid JSON: ${detail}`);
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new CLIError(".claude-plugin/plugin.json must be a JSON object");
  }
  const obj = parsed as Record<string, unknown>;
  if (typeof obj["name"] !== "string" || obj["name"].trim() === "") {
    throw new CLIError(
      ".claude-plugin/plugin.json must include a non-empty 'name' field",
    );
  }
  return obj as PluginManifest;
}

/**
 * Walk a cloned plugin tree and return every file as a base64 entry.
 *
 * - skips .git/ entirely (the API does not need git history; trees are content-addressed)
 * - returns paths POSIX-normalized so the sha is host-agnostic
 * - aborts with CLIError if cumulative size exceeds MAX_TREE_BYTES
 *   (we surface this BEFORE the network call so users do not wait minutes
 *   for a payload the API would reject)
 */
interface TreeWalkState {
  readonly rootDir: string;
  readonly entries: PluginFileEntry[];
  totalBytes: number;
}

function readFileEntry(state: TreeWalkState, abs: string): PluginFileEntry {
  // WHY: paths POSIX-normalized so the API-side sha256 is host-agnostic.
  const rel = path.relative(state.rootDir, abs).split(path.sep).join("/");
  const content = fs.readFileSync(abs);
  state.totalBytes += content.byteLength;
  if (state.totalBytes > MAX_TREE_BYTES) {
    throw new CLIError(
      `plugin tree exceeds ${MAX_TREE_BYTES} bytes (${MAX_TREE_BYTES / 1024 / 1024} MiB); refusing to upload`,
    );
  }
  return { rel_path: rel, content_b64: content.toString("base64") };
}

function walkTreeInto(state: TreeWalkState, dir: string): void {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === ".git") continue;
    const abs = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      walkTreeInto(state, abs);
      continue;
    }
    // WHY: skip symlinks, sockets, devices - we only ship plain files.
    if (!entry.isFile()) continue;
    state.entries.push(readFileEntry(state, abs));
  }
}

export function walkPluginTree(rootDir: string): PluginFileEntry[] {
  const state: TreeWalkState = { rootDir, entries: [], totalBytes: 0 };
  walkTreeInto(state, rootDir);
  // Stable order so the API-side sha256 is reproducible across runs.
  state.entries.sort((a, b) => (a.rel_path < b.rel_path ? -1 : a.rel_path > b.rel_path ? 1 : 0));
  return state.entries;
}
