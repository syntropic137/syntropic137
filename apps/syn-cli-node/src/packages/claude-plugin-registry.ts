// See ADR-066: this registry lives in the CLI tier per the thin-API rule.
//
// Local CLI registry of installed claude plugins. Mirrors the workflow
// `installed.json` registry in packages/resolver.ts but lives at a separate
// path so the two domains stay independent. The API is the source of truth
// for "what's in the lock"; this registry is a CLI-side cache that lets
// `syn claude-plugin install` skip re-fetching and the workflow-install
// pre-flight skip API round-trips for plugins it already has on disk.

import fs from "node:fs";
import path from "node:path";
import { z } from "zod";
import { synPath, readJsonFile } from "../persistence/store.js";
import { printError } from "../output/console.js";

export const ClaudePluginInstallationRecordSchema = z.object({
  name: z.string(),
  version: z.string(),
  source_url: z.string(),
  resolved_sha: z.string(),
  installed_at: z.string(),
  // WHY: the registry name when the plugin was installed via marketplace
  // (Feature 2 of #726); null when installed by direct ref.
  marketplace_source: z.string().nullable(),
});
export type ClaudePluginInstallationRecord = z.infer<
  typeof ClaudePluginInstallationRecordSchema
>;

export const ClaudePluginRegistrySchema = z.object({
  entries: z.array(ClaudePluginInstallationRecordSchema).default([]),
});
export type ClaudePluginRegistry = z.infer<typeof ClaudePluginRegistrySchema>;

const REGISTRY_PATH = synPath("claude-plugins", "installed.json");
const EMPTY: ClaudePluginRegistry = { entries: [] };

export function registryPath(): string {
  return REGISTRY_PATH;
}

export function loadInstalled(): ClaudePluginRegistry {
  // WHY: readJsonFile silently returns the fallback on parse error. We want
  // to warn the user once when their on-disk registry is corrupt so they
  // know why "already installed" detection is being skipped.
  if (fs.existsSync(REGISTRY_PATH)) {
    try {
      const content = fs.readFileSync(REGISTRY_PATH, "utf-8");
      const parsed: unknown = JSON.parse(content);
      return ClaudePluginRegistrySchema.parse(parsed);
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err);
      printError(
        `claude-plugin registry at ${REGISTRY_PATH} is corrupt; ignoring: ${detail}`,
      );
      return EMPTY;
    }
  }
  return readJsonFile(REGISTRY_PATH, ClaudePluginRegistrySchema, EMPTY);
}

export function saveInstalled(registry: ClaudePluginRegistry): void {
  // WHY: atomic via tmp+rename so a crashed write never leaves a half-file
  // that would trigger the corrupt-registry warning on next read.
  const dir = path.dirname(REGISTRY_PATH);
  fs.mkdirSync(dir, { recursive: true });
  const tmp = `${REGISTRY_PATH}.tmp-${process.pid}-${Date.now()}`;
  fs.writeFileSync(tmp, JSON.stringify(registry, null, 2) + "\n", "utf-8");
  fs.renameSync(tmp, REGISTRY_PATH);
}

export interface RecordOptions {
  readonly name: string;
  readonly version: string;
  readonly source_url: string;
  readonly resolved_sha: string;
  readonly marketplace_source?: string | null;
}

export function recordInstallation(opts: RecordOptions): void {
  const registry = loadInstalled();
  const next: ClaudePluginInstallationRecord = {
    name: opts.name,
    version: opts.version,
    source_url: opts.source_url,
    resolved_sha: opts.resolved_sha,
    installed_at: new Date().toISOString(),
    marketplace_source: opts.marketplace_source ?? null,
  };
  // WHY: dedup by (name, version); newer record wins so an upgrade or
  // re-install (e.g. via --force) refreshes resolved_sha and timestamp.
  const filtered = registry.entries.filter(
    (e) => !(e.name === opts.name && e.version === opts.version),
  );
  saveInstalled({ entries: [...filtered, next] });
}

export function findInstalled(
  name: string,
  version: string,
): ClaudePluginInstallationRecord | null {
  const registry = loadInstalled();
  return (
    registry.entries.find(
      (e) => e.name === name && e.version === version,
    ) ?? null
  );
}

export function listInstalled(): ClaudePluginInstallationRecord[] {
  const registry = loadInstalled();
  return [...registry.entries].sort((a, b) =>
    a.name === b.name
      ? a.version.localeCompare(b.version)
      : a.name.localeCompare(b.name),
  );
}

export function removeInstalled(name: string, version: string): boolean {
  const registry = loadInstalled();
  const before = registry.entries.length;
  const next = registry.entries.filter(
    (e) => !(e.name === name && e.version === version),
  );
  if (next.length === before) return false;
  saveInstalled({ entries: next });
  return true;
}
