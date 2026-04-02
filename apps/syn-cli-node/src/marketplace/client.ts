import fs from "node:fs";
import path from "node:path";
import { synPath, readJsonFile, writeJsonFile } from "../persistence/store.js";
import {
  type CachedMarketplace,
  CachedMarketplaceSchema,
  type MarketplaceIndex,
  MarketplaceIndexSchema,
  type MarketplacePluginEntry,
  type RegistryConfig,
  RegistryConfigSchema,
  type RegistryEntry,
} from "./models.js";
import { gitClone, gitLsRemote, makeTempDir, removeTempDir } from "../packages/git.js";

const REGISTRIES_PATH = synPath("registries.json");
const CACHE_DIR = synPath("marketplace", "cache");
const CACHE_TTL_MS = 4 * 60 * 60 * 1000; // 4 hours

const SAFE_NAME_RE = /^[a-zA-Z0-9][a-zA-Z0-9._-]*$/;

export function validateRegistryName(name: string): string {
  if (!SAFE_NAME_RE.test(name) || name.includes("..")) {
    throw new Error(
      `Invalid registry name '${name}': ` +
        "must start with alphanumeric character and contain only " +
        "letters, digits, hyphens, underscores, and dots",
    );
  }
  return name;
}

// ---------------------------------------------------------------------------
// Registry I/O
// ---------------------------------------------------------------------------

export function loadRegistries(): RegistryConfig {
  const fallback: RegistryConfig = { version: 1, registries: {} };
  return readJsonFile(REGISTRIES_PATH, RegistryConfigSchema, fallback);
}

export function saveRegistries(config: RegistryConfig): void {
  writeJsonFile(REGISTRIES_PATH, config);
}

// ---------------------------------------------------------------------------
// Cache I/O
// ---------------------------------------------------------------------------

export function loadCachedIndex(
  registryName: string,
): CachedMarketplace | null {
  validateRegistryName(registryName);
  const cachePath = path.join(CACHE_DIR, `${registryName}.json`);
  if (!fs.existsSync(cachePath)) return null;
  try {
    const content = fs.readFileSync(cachePath, "utf-8");
    return CachedMarketplaceSchema.parse(JSON.parse(content));
  } catch {
    return null;
  }
}

export function saveCachedIndex(
  registryName: string,
  cached: CachedMarketplace,
): void {
  validateRegistryName(registryName);
  fs.mkdirSync(CACHE_DIR, { recursive: true });
  const cachePath = path.join(CACHE_DIR, `${registryName}.json`);
  writeJsonFile(cachePath, cached);
}

export function isCacheStale(cached: CachedMarketplace): boolean {
  try {
    const fetched = new Date(cached.fetched_at).getTime();
    if (isNaN(fetched)) return true;
    return Date.now() - fetched > CACHE_TTL_MS;
  } catch {
    return true;
  }
}

// ---------------------------------------------------------------------------
// Fetching
// ---------------------------------------------------------------------------

export async function fetchMarketplaceJson(
  repo: string,
  ref = "main",
): Promise<MarketplaceIndex> {
  const url = `https://github.com/${repo}.git`;
  const tmpdir = makeTempDir("syn-mkt-");
  try {
    await gitClone(url, ref, tmpdir);

    const marketplacePath = path.join(tmpdir, "marketplace.json");
    if (!fs.existsSync(marketplacePath)) {
      throw new Error(`No marketplace.json found in ${repo}`);
    }

    const content = fs.readFileSync(marketplacePath, "utf-8");
    const data: unknown = JSON.parse(content);
    if (typeof data !== "object" || data === null || Array.isArray(data)) {
      throw new Error("marketplace.json must be a JSON object");
    }

    const index = MarketplaceIndexSchema.parse(data);

    if (index.syntropic137.type !== "workflow-marketplace") {
      throw new Error(
        `Expected syntropic137.type='workflow-marketplace', got '${index.syntropic137.type}'`,
      );
    }

    return index;
  } finally {
    removeTempDir(tmpdir);
  }
}

export async function refreshIndex(
  registryName: string,
  entry: RegistryEntry,
  force = false,
): Promise<MarketplaceIndex> {
  if (!force) {
    const cached = loadCachedIndex(registryName);
    if (cached !== null && !isCacheStale(cached)) {
      return cached.index;
    }
  }

  const index = await fetchMarketplaceJson(entry.repo, entry.ref);
  saveCachedIndex(registryName, {
    fetched_at: new Date().toISOString(),
    index,
  });
  return index;
}

// ---------------------------------------------------------------------------
// Discovery
// ---------------------------------------------------------------------------

function matchesQuery(
  plugin: MarketplacePluginEntry,
  query: string,
): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  return (
    plugin.name.toLowerCase().includes(q) ||
    plugin.description.toLowerCase().includes(q) ||
    plugin.category.toLowerCase().includes(q) ||
    plugin.tags.some((t) => t.toLowerCase().includes(q))
  );
}

function matchesFilters(
  plugin: MarketplacePluginEntry,
  query: string,
  category: string | null,
  tag: string | null,
): boolean {
  if (!matchesQuery(plugin, query)) return false;
  if (category && plugin.category.toLowerCase() !== category.toLowerCase())
    return false;
  if (tag && !plugin.tags.some((t) => t.toLowerCase() === tag.toLowerCase()))
    return false;
  return true;
}

async function getRegistryIndex(
  name: string,
  entry: RegistryEntry,
): Promise<MarketplaceIndex | null> {
  try {
    return await refreshIndex(name, entry);
  } catch {
    return null;
  }
}

export async function searchAllRegistries(
  query = "",
  opts?: { category?: string | null; tag?: string | null },
): Promise<Array<[string, MarketplacePluginEntry]>> {
  const config = loadRegistries();
  const results: Array<[string, MarketplacePluginEntry]> = [];
  const category = opts?.category ?? null;
  const tag = opts?.tag ?? null;

  for (const [name, entry] of Object.entries(config.registries)) {
    const index = await getRegistryIndex(name, entry);
    if (index === null) continue;
    for (const plugin of index.plugins) {
      if (matchesFilters(plugin, query, category, tag)) {
        results.push([name, plugin]);
      }
    }
  }

  return results;
}

export async function resolvePluginByName(
  name: string,
  registry?: string | null,
): Promise<[string, RegistryEntry, MarketplacePluginEntry] | null> {
  const config = loadRegistries();

  const targets: Array<[string, RegistryEntry]> = registry
    ? config.registries[registry]
      ? [[registry, config.registries[registry]]]
      : []
    : Object.entries(config.registries);

  for (const [regName, entry] of targets) {
    const index = await getRegistryIndex(regName, entry);
    if (index === null) continue;
    for (const plugin of index.plugins) {
      if (plugin.name === name) {
        return [regName, entry, plugin];
      }
    }
  }

  return null;
}

export { gitLsRemote as getGitHeadSha };
