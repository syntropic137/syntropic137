// See ADR-066: pre-flight runs in the CLI tier so the API never has to
// reason about plugin sources at workflow-install time.
/**
 * Workflow-install pre-flight for `claude_plugins:` declarations.
 *
 * Walks the resolved package directory, parses every workflow YAML it
 * contains, collects all declared claude plugin refs (workflow- and
 * phase-scope), de-duplicates by (source_url, version), and:
 *
 *   1. Skips refs already present in the lock projection (cheap GET).
 *   2. For the remainder, runs the same clone+register flow as
 *      `syn claude-plugin install` against each.
 *
 * If ANY ref fails, the whole pre-flight aborts BEFORE the workflow POSTs
 * mutate state. This preserves the user-visible "atomic install" property
 * documented in the redesign plan.
 *
 * Workflows without `claude_plugins:` incur zero overhead - we only walk the
 * file tree and parse YAML, which is fast and local.
 */

import fs from "node:fs";
import path from "node:path";
import { CLIError } from "../framework/errors.js";
import { api } from "../client/typed.js";
import { parseYaml } from "./yaml.js";
import {
  parseClaudePluginRef,
  type ParsedClaudePluginRef,
} from "./claude-plugin.js";
import { registerClaudePluginFromRef } from "../commands/claude-plugin/install.js";
import { findInstalled, recordInstallation } from "./claude-plugin-registry.js";
import { print, printDim, printSuccess } from "../output/console.js";
import { style, CYAN } from "../output/ansi.js";

export interface PreflightResult {
  /** Refs that were missing from the lock and got registered just now. */
  readonly registered: readonly ParsedClaudePluginRef[];
  /** Refs already present in the lock; skipped. */
  readonly skipped: readonly ParsedClaudePluginRef[];
}

/** Recursively find every *.yaml/*.yml file under a directory. */
function findYamlFiles(root: string): string[] {
  const out: string[] = [];
  function walk(dir: string): void {
    if (!fs.existsSync(dir) || !fs.statSync(dir).isDirectory()) return;
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      if (entry.name === ".git" || entry.name === "node_modules") continue;
      const abs = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        walk(abs);
        continue;
      }
      if (!entry.isFile()) continue;
      const lower = entry.name.toLowerCase();
      if (lower.endsWith(".yaml") || lower.endsWith(".yml")) {
        out.push(abs);
      }
    }
  }
  walk(root);
  return out;
}

/**
 * Extract every `claude_plugins:` declaration from a parsed YAML doc.
 * Looks at top-level and inside any `phases[].claude_plugins`.
 */
function extractRefStrings(doc: unknown): string[] {
  const refs: string[] = [];
  if (typeof doc !== "object" || doc === null || Array.isArray(doc)) return refs;
  const obj = doc as Record<string, unknown>;
  collectRefs(obj["claude_plugins"], refs);
  const phases = obj["phases"];
  if (Array.isArray(phases)) {
    for (const phase of phases) {
      if (typeof phase === "object" && phase !== null && !Array.isArray(phase)) {
        collectRefs((phase as Record<string, unknown>)["claude_plugins"], refs);
      }
    }
  }
  return refs;
}

function collectRefs(value: unknown, into: string[]): void {
  if (!Array.isArray(value)) return;
  for (const item of value) {
    if (typeof item === "string") {
      into.push(item);
      continue;
    }
    // Verbose mapping form - stringify into "<source>@<version>" so we share
    // the parser. We only support source/source_url + version here; explicit
    // name overrides are dropped (the manifest's name is canonical).
    if (typeof item === "object" && item !== null && !Array.isArray(item)) {
      const obj = item as Record<string, unknown>;
      const src = obj["source"] ?? obj["source_url"];
      const ver = obj["version"];
      if (typeof src === "string" && typeof ver === "string") {
        into.push(`${src}@${ver}`);
      }
    }
  }
}

/**
 * Cheap "is this (name, version) in the lock?" check.
 * 404 means missing; any other status means we surface as failure.
 */
async function isInLock(name: string, version: string): Promise<boolean> {
  const result = await api.GET("/claude-plugins/{name}/{version}", {
    params: { path: { name, version } },
  });
  if (result.error === undefined) return true;
  // openapi-fetch normalizes 404 into result.error with the response body. We
  // accept "any error == not present" here; the subsequent register flow will
  // surface real connectivity issues with a clearer message.
  return false;
}

export async function runClaudePluginPreflight(
  packagePath: string,
): Promise<PreflightResult | null> {
  const yamlFiles = findYamlFiles(packagePath);
  const seen = new Map<string, ParsedClaudePluginRef>();

  for (const file of yamlFiles) {
    let parsed: unknown;
    try {
      parsed = parseYaml(fs.readFileSync(file, "utf-8"));
    } catch {
      // Non-workflow YAMLs may not parse cleanly with our minimal parser; skip.
      continue;
    }
    for (const refString of extractRefStrings(parsed)) {
      const ref = parseClaudePluginRef(refString);
      const key = `${ref.source_url}@${ref.version}`;
      if (!seen.has(key)) seen.set(key, ref);
    }
  }

  if (seen.size === 0) return null;

  print("");
  print(style(`Resolving ${seen.size} claude plugin(s)...`, CYAN));

  const registered: ParsedClaudePluginRef[] = [];
  const skipped: ParsedClaudePluginRef[] = [];

  for (const ref of seen.values()) {
    // WHY (#726): consult the local CLI registry first to avoid an API
    // round-trip for plugins we already know are locked. The API check
    // remains as fallback because the local cache may be wiped or
    // out-of-date between machines.
    if (findInstalled(ref.name, ref.version)) {
      printDim(`  - ${ref.name}@${ref.version} already locked (cache), skipping`);
      skipped.push(ref);
      continue;
    }
    const present = await isInLock(ref.name, ref.version);
    if (present) {
      printDim(`  - ${ref.name}@${ref.version} already locked, skipping`);
      skipped.push(ref);
      continue;
    }
    try {
      const result = await registerClaudePluginFromRef(ref);
      // WHY: keep the local cache in sync so subsequent pre-flights skip
      // the API round-trip too.
      recordInstallation({
        name: result.name,
        version: result.version,
        source_url: ref.source_url,
        resolved_sha: result.sha256,
        marketplace_source: null,
      });
      registered.push(ref);
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err);
      throw new CLIError(
        `claude plugin pre-flight failed for ${ref.source_url}@${ref.version}: ${detail}\n` +
          "  No workflows were installed.",
      );
    }
  }

  if (registered.length > 0) {
    printSuccess(`Registered ${registered.length} new claude plugin(s).`);
  }
  return { registered, skipped };
}
