// See ADR-066: pre-flight runs in the CLI tier so the API never has to
// reason about plugin sources at workflow-install time.
/**
 * Workflow-install pre-flight for `claude_plugins:` declarations.
 *
 * Reads the workflows the resolver accepted, collects all declared claude
 * plugin refs (workflow- and phase-scope) from their definitions,
 * de-duplicates by (source_url, version, name) -- matching
 * the Python lock key, so two aliases of the same source register as two
 * distinct lock entries -- and:
 *
 *   1. Skips refs already present in the lock projection (cheap GET).
 *   2. For the remainder, runs the same clone+register flow as
 *      `syn claude-plugin install` against each.
 *
 * If ANY ref fails, the whole pre-flight aborts BEFORE the workflow POSTs
 * mutate state. This preserves the user-visible "atomic install" property
 * documented in the redesign plan.
 *
 * WHY the resolved definitions and not the package's YAML files (#1949): the
 * resolver decides which documents are workflows, and a file it skipped (a
 * lockfile, a tool config) must not be able to register a plugin or abort the
 * install. Rediscovering documents here would be a second, divergent judgment.
 *
 * Workflows without `claude_plugins:` incur zero overhead - nothing is read
 * beyond the definitions already in memory.
 */

import { CLIError } from "../framework/errors.js";
import { api } from "../client/typed.js";
import type { ResolvedWorkflow } from "./models.js";
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

/**
 * Extract every `claude_plugins:` declaration from a workflow definition.
 * Looks at top-level and inside any `phases[].claude_plugins`.
 */
function extractRefItems(doc: unknown): unknown[] {
  const refs: unknown[] = [];
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

function refFromVerbose(item: unknown): ParsedClaudePluginRef | null {
  // WHY: the verbose mapping's source+version share the string parser via
  // "<source>@<version>"; an explicit `name:` override is preserved because
  // the lock key is (source_url, version, name) -- dropping it would register
  // the manifest name and then fail the install-time lock lookup for the
  // alias (PR #764 review).
  if (typeof item !== "object" || item === null || Array.isArray(item)) return null;
  const obj = item as Record<string, unknown>;
  const src = obj["source"] ?? obj["source_url"];
  const ver = obj["version"];
  if (typeof src !== "string" || typeof ver !== "string") return null;
  const base = parseClaudePluginRef(`${src}@${ver}`);
  const name = obj["name"];
  if (typeof name === "string" && name.trim() !== "") {
    return { ...base, name: name.trim(), name_overridden: true };
  }
  return base;
}

function refFromItem(item: unknown): ParsedClaudePluginRef | null {
  if (typeof item === "string") return parseClaudePluginRef(item);
  return refFromVerbose(item);
}

function collectRefs(value: unknown, into: unknown[]): void {
  if (!Array.isArray(value)) return;
  for (const item of value) {
    into.push(item);
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

function claudePluginLockKey(ref: ParsedClaudePluginRef): string {
  // WHY name in the key: the lock key is (source_url, version, name);
  // two aliases of the same source/version are two distinct entries.
  return `${ref.source_url}\0${ref.version}\0${ref.name}`;
}

function collectUniqueRefsFromDefinition(
  definition: Record<string, unknown>,
  seen: Map<string, ParsedClaudePluginRef>,
): void {
  for (const item of extractRefItems(definition)) {
    const ref = refFromItem(item);
    if (ref === null) continue;
    const key = claudePluginLockKey(ref);
    if (!seen.has(key)) seen.set(key, ref);
  }
}

function collectUniqueRefs(
  workflows: readonly ResolvedWorkflow[],
): Map<string, ParsedClaudePluginRef> {
  const seen = new Map<string, ParsedClaudePluginRef>();
  for (const workflow of workflows) {
    collectUniqueRefsFromDefinition(workflow.definition, seen);
  }
  return seen;
}

async function isRefAlreadyLocked(ref: ParsedClaudePluginRef): Promise<"cache" | "api" | null> {
  // WHY (#726): consult the local CLI registry first to avoid an API
  // round-trip for plugins we already know are locked. The API check
  // remains as fallback because the local cache may be wiped or
  // out-of-date between machines.
  if (findInstalled(ref.name, ref.version)) return "cache";
  if (await isInLock(ref.name, ref.version)) return "api";
  return null;
}

async function registerSingleRef(ref: ParsedClaudePluginRef): Promise<void> {
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
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err);
    throw new CLIError(
      `claude plugin pre-flight failed for ${ref.source_url}@${ref.version}: ${detail}\n` +
        "  No workflows were installed.",
    );
  }
}

async function processRef(
  ref: ParsedClaudePluginRef,
  registered: ParsedClaudePluginRef[],
  skipped: ParsedClaudePluginRef[],
): Promise<void> {
  const lockHit = await isRefAlreadyLocked(ref);
  if (lockHit === "cache") {
    printDim(`  - ${ref.name}@${ref.version} already locked (cache), skipping`);
    skipped.push(ref);
    return;
  }
  if (lockHit === "api") {
    printDim(`  - ${ref.name}@${ref.version} already locked, skipping`);
    skipped.push(ref);
    return;
  }
  await registerSingleRef(ref);
  registered.push(ref);
}

export async function runClaudePluginPreflight(
  workflows: readonly ResolvedWorkflow[],
): Promise<PreflightResult | null> {
  const seen = collectUniqueRefs(workflows);

  if (seen.size === 0) return null;

  print("");
  print(style(`Resolving ${seen.size} claude plugin(s)...`, CYAN));

  const registered: ParsedClaudePluginRef[] = [];
  const skipped: ParsedClaudePluginRef[] = [];

  for (const ref of seen.values()) {
    await processRef(ref, registered, skipped);
  }

  if (registered.length > 0) {
    printSuccess(`Registered ${registered.length} new claude plugin(s).`);
  }
  return { registered, skipped };
}
