/**
 * Register the skills a workflow plugin declares, at install time.
 *
 * WHY at install: without this a workflow declaring `skills:` installs
 * cleanly and then dies at execution with SkillNotRegistered, after the user
 * has committed to a run. Failing here costs nothing.
 *
 * Mirrors claude-plugin-preflight.ts, with one structural difference: it reads
 * the resolved workflow definitions rather than re-walking the package's YAML
 * files, because it must REWRITE bundled refs in those definitions before they
 * are uploaded. See `pinBundledRefsInDefinition`.
 */
import * as fs from "node:fs";
import * as path from "node:path";

import { CLIError } from "../framework/errors.js";
import { printDim, printSuccess, print } from "../output/console.js";
import { style, CYAN } from "../output/ansi.js";
import { api, unwrap } from "../client/typed.js";
import { gitClone, makeTempDir, removeTempDir } from "./git.js";
import type { ResolvedWorkflow } from "./models.js";
import {
  parseSkillEntry,
  pinBundledRef,
  type BundledSkillRef,
  type ExternalSkillRef,
  type ParsedSkillRef,
} from "./skill-ref.js";
import { readSkillTree, skillDirInClone, type SkillFilePayload } from "./skill-tree.js";

export interface SkillPreflightResult {
  /** Refs that were missing and got registered just now. */
  readonly registered: readonly ExternalSkillRef[];
  /** Refs whose content hash was already stored; no upload performed. */
  readonly skipped: readonly ExternalSkillRef[];
}

const SKILLS_KEY = "skills";
const PHASES_KEY = "phases";

function asRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

/**
 * Every `skills:` list in a definition: workflow scope first, then each phase.
 *
 * Returned as live references to the definition's own arrays so callers can
 * rewrite entries in place.
 */
function skillArraysIn(definition: Record<string, unknown>): unknown[][] {
  const arrays: unknown[][] = [];

  const top = definition[SKILLS_KEY];
  if (Array.isArray(top)) arrays.push(top);

  const phases = definition[PHASES_KEY];
  if (Array.isArray(phases)) {
    for (const phase of phases) {
      const record = asRecord(phase);
      if (record === null) continue;
      const phaseSkills = record[SKILLS_KEY];
      if (Array.isArray(phaseSkills)) arrays.push(phaseSkills);
    }
  }
  return arrays;
}

function refKey(ref: ParsedSkillRef): string {
  return ref.kind === "bundled"
    ? `bundled ${ref.localPath} ${ref.skillName}`
    : `${ref.sourceUrl} ${ref.version} ${ref.skillName}`;
}

/**
 * Every skill ref the given workflows declare, from workflow AND phase scope.
 *
 * Deduped so a skill declared at both scopes is registered once.
 */
export function collectSkillRefs(workflows: readonly ResolvedWorkflow[]): ParsedSkillRef[] {
  const seen = new Map<string, ParsedSkillRef>();
  for (const workflow of workflows) {
    for (const entries of skillArraysIn(workflow.definition)) {
      for (const entry of entries) {
        for (const ref of parseSkillEntry(entry)) {
          seen.set(refKey(ref), ref);
        }
      }
    }
  }
  return [...seen.values()];
}

/**
 * Resolve a bundled skill path and prove it stays inside the plugin.
 *
 * WHY resolve rather than trust the parsed shape: the directory this returns is
 * read and uploaded, so a plugin that escaped it could exfiltrate arbitrary
 * files from the machine running the install. `parseSkillEntry` already rejects
 * `..` segments, but a symlink inside the plugin points outward without any
 * `..` appearing in the declared path, so containment is re-proved here against
 * the real path.
 */
function bundledSkillDir(packagePath: string, ref: BundledSkillRef): string {
  const root = fs.realpathSync(path.resolve(packagePath));
  const candidate = path.resolve(root, ref.localPath);

  const resolved = fs.existsSync(candidate) ? fs.realpathSync(candidate) : candidate;
  if (resolved !== root && !resolved.startsWith(root + path.sep)) {
    throw new CLIError(
      `bundled skill '${ref.localPath}' resolves outside the plugin (${resolved}).\n` +
        "  A plugin may only bundle skills from within itself. No workflows were installed.",
    );
  }
  return resolved;
}

function readBundledTree(packagePath: string, ref: BundledSkillRef): SkillFilePayload[] {
  try {
    return readSkillTree(bundledSkillDir(packagePath, ref));
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err);
    throw new CLIError(
      `bundled skill '${ref.localPath}' could not be read: ${detail}\n` +
        "  No workflows were installed.",
    );
  }
}

/** Serialize a pinned ref as the verbose mapping form the domain accepts. */
function toVerboseEntry(ref: ExternalSkillRef): Record<string, unknown> {
  return { source: ref.sourceUrl, version: ref.version, name: ref.skillName };
}

/**
 * Rewrite every `skills:` entry into an explicitly pinned mapping.
 *
 * WHY this is necessary, not cosmetic: the stored workflow template is what
 * run-time resolution reads, and it looks skills up by
 * (source_url, version, skill_name). A bundled entry like
 * `./skills/repo-conventions` carries no version, and the server cannot
 * compute one - it never sees the plugin directory. So the CLI resolves the
 * bundled path to its content hash here, exactly as it does for prompt_file,
 * and uploads a document in which every skill is pinned.
 *
 * External refs are rewritten to the same mapping form for uniformity; the
 * identity they denote is unchanged.
 */
export function pinBundledRefsInDefinition(
  definition: Record<string, unknown>,
  packagePath: string,
): void {
  for (const entries of skillArraysIn(definition)) {
    const pinned: Record<string, unknown>[] = [];
    for (const entry of entries) {
      for (const ref of parseSkillEntry(entry)) {
        pinned.push(
          toVerboseEntry(
            ref.kind === "bundled" ? pinBundledRef(ref, readBundledTree(packagePath, ref)) : ref,
          ),
        );
      }
    }
    entries.splice(0, entries.length, ...pinned);
  }
}

const HASH_VERSION_PREFIX = "sha256-";

/**
 * Is this ref already stored, and does the stored content match what we pinned?
 *
 * WHY the sha is checked and not just the boolean: for a bundled skill the
 * version segment IS a content commitment (`sha256-<tree hash>`), but nothing
 * server-side proves that the tree stored under that triple actually hashes to
 * it - `RegisterSkillHandler` returns an existing aggregate before hashing the
 * submitted files. So a registration made under a hash-shaped version with
 * different content would be silently adopted here, and the workspace would
 * receive content the plugin never declared. The returned `resolved_sha` is
 * what makes the commitment checkable, so we check it and fail closed.
 *
 * A lookup that errors is an error, never a cache miss: treating a 401 or 500
 * as "not registered" would send us on to clone a remote and attempt an upload
 * that cannot succeed.
 */
async function isRegistered(ref: ExternalSkillRef): Promise<boolean> {
  const data = unwrap(
    await api.GET("/skills/registrations", {
      params: {
        query: {
          source_url: ref.sourceUrl,
          version: ref.version,
          skill_name: ref.skillName,
        },
      },
    }),
    `Failed to look up skill ${ref.skillName}@${ref.version}`,
  );

  if (!data.registered) return false;

  if (ref.version.startsWith(HASH_VERSION_PREFIX)) {
    const pinned = ref.version.slice(HASH_VERSION_PREFIX.length);
    if (data.resolved_sha !== pinned) {
      throw new CLIError(
        `skill ${ref.skillName} is registered under ${ref.version} but its stored content ` +
          `hashes to ${data.resolved_sha ?? "(none)"}.\n` +
          "  The version pins the content, so this registration does not match what the " +
          "plugin declares.\n  Refusing to reuse it. No workflows were installed.",
      );
    }
  }
  return true;
}


async function readExternalTree(ref: ExternalSkillRef): Promise<SkillFilePayload[]> {
  const tmpdir = makeTempDir("syn-skill-");
  try {
    print(`  Cloning ${style(ref.sourceUrl, CYAN)}@${ref.version}...`);
    await gitClone(ref.sourceUrl, ref.version, tmpdir);
    return readSkillTree(skillDirInClone(tmpdir, ref.skillName));
  } catch (err) {
    if (err instanceof CLIError) throw err;
    const detail = err instanceof Error ? err.message : String(err);
    throw new CLIError(
      `skill pre-flight failed for ${ref.sourceUrl}@${ref.version}: ${detail}\n` +
        "  No workflows were installed.",
    );
  } finally {
    removeTempDir(tmpdir);
  }
}

async function registerRef(ref: ExternalSkillRef, files: SkillFilePayload[]): Promise<void> {
  unwrap(
    await api.POST("/skills/registrations", {
      body: {
        source_url: ref.sourceUrl,
        version: ref.version,
        skill_name: ref.skillName,
        files: files as { rel_path: string; content_base64: string }[],
      },
    }),
    `Failed to register skill ${ref.skillName}`,
  );
}

/**
 * Register every skill the given workflows declare that is not already stored,
 * and pin bundled refs in the definitions that are about to be uploaded.
 *
 * Bundled trees are read from the already-cloned plugin; external refs are
 * shallow-cloned once. A ref whose content hash is already registered performs
 * no network work beyond the lookup - the hash IS the cache.
 */
export async function runSkillPreflight(
  packagePath: string,
  workflows: readonly ResolvedWorkflow[],
): Promise<SkillPreflightResult> {
  const refs = collectSkillRefs(workflows);
  if (refs.length === 0) return { registered: [], skipped: [] };

  print("");
  print(style(`Resolving ${refs.length} skill(s)...`, CYAN));

  const registered: ExternalSkillRef[] = [];
  const skipped: ExternalSkillRef[] = [];

  for (const ref of refs) {
    // Bundled trees must be read to know their identity at all, so this is
    // done before the lookup rather than after it.
    const bundledFiles = ref.kind === "bundled" ? readBundledTree(packagePath, ref) : null;
    const pinned = ref.kind === "bundled" ? pinBundledRef(ref, bundledFiles ?? []) : ref;

    if (await isRegistered(pinned)) {
      skipped.push(pinned);
      printDim(`  skill ${pinned.skillName}@${pinned.version} already registered`);
      continue;
    }

    const files = bundledFiles ?? (await readExternalTree(pinned));
    await registerRef(pinned, files);
    registered.push(pinned);
    printSuccess(`  registered skill ${pinned.skillName}@${pinned.version}`);
  }

  // Rewrite the definitions only after every ref resolved, so a failure
  // cannot leave half-pinned documents behind.
  for (const workflow of workflows) {
    pinBundledRefsInDefinition(workflow.definition, packagePath);
  }

  return { registered, skipped };
}
