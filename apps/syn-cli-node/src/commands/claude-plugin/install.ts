// See ADR-066: git work happens in this CLI tier per the thin-API rule.
// We clone, walk the tree, and POST a structured payload; the API never
// shells out.
/**
 * `syn claude-plugin install <ref> [--global] [--plugin <name>] [--force]`
 *
 * Mirrors the workflow-install pattern (apps/syn-cli-node/src/commands/workflow/install.ts):
 * clone locally, read the manifest, walk the tree, then POST. Optional
 * --global flag flips the registered plugin into the global set in a
 * second round-trip so users do not need to chain two commands manually.
 *
 * Three install paths in priority order (#726, #763):
 *
 *   1. Bare name (e.g. `sdlc`): resolved through configured marketplaces.
 *      The marketplace entry's `source` subdir is the plugin tree.
 *
 *   2. `org/repo@version` AND a `marketplace.json` exists at clone root:
 *      treat the repo as a multi-plugin marketplace. `--plugin <name>`
 *      selects which plugin's subdir to register; without it we error
 *      with the available plugin names.
 *
 *   3. `org/repo@version` (or full URL) with a `.claude-plugin/plugin.json`
 *      at the clone root: original single-plugin behavior, unchanged.
 *
 * --force bypasses the local "already installed" cache and re-registers.
 */

import fs from "node:fs";
import path from "node:path";
import type { CommandDef, ParsedArgs } from "../../framework/command.js";
import { CLIError } from "../../framework/errors.js";
import { api, unwrap } from "../../client/typed.js";
import { gitClone, makeTempDir, removeTempDir } from "../../packages/git.js";
import {
  parseClaudePluginRef,
  readPluginManifest,
  walkPluginTree,
  type ParsedClaudePluginRef,
} from "../../packages/claude-plugin.js";
import {
  findInstalled,
  recordInstallation,
} from "../../packages/claude-plugin-registry.js";
import {
  resolveFromMarketplace,
  type ResolvedMarketplaceArtifact,
} from "../../marketplace/client.js";
import { MarketplaceIndexSchema } from "../../marketplace/models.js";
import { print, printSuccess, printDim } from "../../output/console.js";
import { style, BOLD, CYAN } from "../../output/ansi.js";
import { isBarePluginName } from "../workflow/install.js";

export interface RegisterResult {
  readonly name: string;
  readonly version: string;
  readonly sha256: string;
}

interface RegisterPaths {
  readonly pluginRoot: string;
  readonly sourceUrl: string;
  readonly version: string;
  readonly fallbackName: string;
  /**
   * When true, `fallbackName` is an explicit alias from a verbose
   * `claude_plugins` ref and wins over the manifest name. The lock key is
   * (source_url, version, name), so an alias must be registered under the
   * alias or workflow install fails its lock lookup for that name.
   */
  readonly nameOverridden?: boolean;
}

async function registerFromDirectory(paths: RegisterPaths): Promise<RegisterResult> {
  const manifest = readPluginManifest(paths.pluginRoot);
  const files = walkPluginTree(paths.pluginRoot);
  const manifestName =
    typeof manifest["name"] === "string" && manifest["name"].trim() !== ""
      ? manifest["name"]
      : paths.fallbackName;
  const name = paths.nameOverridden === true ? paths.fallbackName : manifestName;

  printDim(`  Uploading ${files.length} file(s)...`);
  const result = unwrap(
    await api.POST("/claude-plugins/registrations", {
      body: {
        source_url: paths.sourceUrl,
        version: paths.version,
        name,
        // The API model accepts arbitrary JSON-shaped manifest content; the
        // generated openapi-typescript type widens it to Record<string, never>
        // for forbid-extra schemas, so we pass through after a structural cast.
        manifest: manifest as unknown as Record<string, never>,
        files,
      },
    }),
    "Failed to register claude plugin",
  );
  return { name: result.name, version: result.version, sha256: result.sha256 };
}

/**
 * Reusable register flow: clone + walk + POST /claude-plugins/registrations.
 * Exposed so the workflow-install pre-flight can reuse it without going
 * through the CLI argv layer.
 */
export async function registerClaudePluginFromRef(
  parsed: ParsedClaudePluginRef,
): Promise<RegisterResult> {
  const tmpdir = makeTempDir("syn-claude-plugin-");
  try {
    print(`Cloning ${style(parsed.source_url, CYAN)}@${parsed.version}...`);
    await gitClone(parsed.source_url, parsed.version, tmpdir);
    return await registerFromDirectory({
      pluginRoot: tmpdir,
      sourceUrl: parsed.source_url,
      version: parsed.version,
      fallbackName: parsed.name,
      nameOverridden: parsed.name_overridden === true,
    });
  } finally {
    removeTempDir(tmpdir);
  }
}

async function addToGlobal(name: string, version: string): Promise<void> {
  unwrap(
    await api.POST("/claude-plugins/global", { body: { name, version } }),
    "Failed to add claude plugin to global set",
  );
}

interface MarketplaceMaybe {
  readonly index: ReturnType<typeof MarketplaceIndexSchema.parse>;
}

function readMarketplaceJsonAt(rootDir: string): MarketplaceMaybe | null {
  // WHY: claude-code marketplaces nest the marketplace.json at
  // .claude-plugin/marketplace.json (per fixture); accept both layouts so
  // we work with marketplaces that put it at the repo root too.
  const candidates = [
    path.join(rootDir, ".claude-plugin", "marketplace.json"),
    path.join(rootDir, "marketplace.json"),
  ];
  for (const candidate of candidates) {
    if (!fs.existsSync(candidate)) continue;
    try {
      const data: unknown = JSON.parse(fs.readFileSync(candidate, "utf-8"));
      return { index: MarketplaceIndexSchema.parse(data) };
    } catch {
      return null;
    }
  }
  return null;
}

function pickPluginFromMarketplace(
  marketplace: MarketplaceMaybe,
  pluginName: string,
  contextLabel: string,
): { source: string; name: string } {
  const match = marketplace.index.plugins.find((p) => p.name === pluginName);
  if (!match) {
    const available = marketplace.index.plugins.map((p) => p.name).join(", ");
    throw new CLIError(
      `Plugin '${pluginName}' not found in ${contextLabel}. Available: ${available || "(none)"}`,
    );
  }
  return { source: match.source, name: match.name };
}

interface RegisterMarketplaceOpts {
  readonly tmpdir: string;
  readonly marketplace: MarketplaceMaybe;
  readonly sourceUrl: string;
  readonly version: string;
  readonly contextLabel: string;
  readonly pluginName: string | null;
}

async function registerFromMarketplaceClone(
  opts: RegisterMarketplaceOpts,
): Promise<RegisterResult> {
  if (!opts.pluginName) {
    const list = opts.marketplace.index.plugins
      .map((p) => `  - ${p.name}`)
      .join("\n");
    throw new CLIError(
      `${opts.contextLabel} is a marketplace with ${opts.marketplace.index.plugins.length} plugins.\n` +
        `Pick one with --plugin <name>:\n${list}`,
    );
  }
  const picked = pickPluginFromMarketplace(
    opts.marketplace,
    opts.pluginName,
    opts.contextLabel,
  );
  // Path-traversal guard: the marketplace.json is third-party content.
  if (picked.source.startsWith("/") || picked.source.includes("..")) {
    throw new CLIError(`Unsafe plugin source path in marketplace: ${picked.source}`);
  }
  const subdir = path.resolve(opts.tmpdir, picked.source.replace(/^\.\//, ""));
  if (!subdir.startsWith(opts.tmpdir)) {
    throw new CLIError(`Plugin source path escapes repository: ${picked.source}`);
  }
  return await registerFromDirectory({
    pluginRoot: subdir,
    sourceUrl: opts.sourceUrl,
    version: opts.version,
    fallbackName: picked.name,
  });
}

interface InstallContext {
  readonly result: RegisterResult;
  readonly sourceUrl: string;
  readonly marketplaceSource: string | null;
}

async function runBareNameInstall(
  source: string,
  ref: string | null,
): Promise<InstallContext | null> {
  const resolved = await resolveFromMarketplace(source, ref);
  if (resolved === null) return null;

  print(
    `Found ${style(resolved.entry.name, BOLD)} in marketplace ${style(resolved.registryName, CYAN)}`,
  );
  try {
    const result = await registerFromDirectory({
      pluginRoot: resolved.packagePath,
      sourceUrl: marketplaceSourceUrl(resolved),
      version: resolved.resolvedRef,
      fallbackName: resolved.entry.name,
    });
    return {
      result,
      sourceUrl: marketplaceSourceUrl(resolved),
      marketplaceSource: resolved.registryName,
    };
  } finally {
    removeTempDir(resolved.tmpdir);
  }
}

function marketplaceSourceUrl(resolved: ResolvedMarketplaceArtifact): string {
  // WHY: registry record keeps the public clone URL (not the local tmpdir),
  // so the lock can be reproduced from a fresh checkout.
  // The marketplace entry doesn't carry the parent repo URL directly; we
  // rebuild it from the registry list. resolveFromMarketplace does not
  // currently surface the parent repo, so we fall back to the entry source
  // path. For now we use the parent repo URL via the registry config
  // lookup is not done here; the cleanest source identifier we have at
  // this point is the marketplace entry's `source` subpath. Callers
  // wanting a fully-qualified URL should look at registry config.
  return `marketplace://${resolved.registryName}/${resolved.entry.name}`;
}

async function runRefInstall(
  ref: string,
  pluginName: string | null,
): Promise<InstallContext> {
  const parsedRef = parseClaudePluginRef(ref);
  const tmpdir = makeTempDir("syn-claude-plugin-");
  try {
    print(`Cloning ${style(parsedRef.source_url, CYAN)}@${parsedRef.version}...`);
    await gitClone(parsedRef.source_url, parsedRef.version, tmpdir);

    const marketplace = readMarketplaceJsonAt(tmpdir);
    if (marketplace !== null) {
      const result = await registerFromMarketplaceClone({
        tmpdir,
        marketplace,
        sourceUrl: parsedRef.source_url,
        version: parsedRef.version,
        contextLabel: ref,
        pluginName,
      });
      return { result, sourceUrl: parsedRef.source_url, marketplaceSource: null };
    }

    if (pluginName) {
      // WHY: --plugin only makes sense for marketplace repos; surface a
      // clear error rather than silently ignoring it.
      throw new CLIError(
        `--plugin was given but ${ref} has no marketplace.json; this is a single-plugin repo.`,
      );
    }

    const result = await registerFromDirectory({
      pluginRoot: tmpdir,
      sourceUrl: parsedRef.source_url,
      version: parsedRef.version,
      fallbackName: parsedRef.name,
    });
    return { result, sourceUrl: parsedRef.source_url, marketplaceSource: null };
  } finally {
    removeTempDir(tmpdir);
  }
}

export const installCommand: CommandDef = {
  name: "install",
  description: "Install a Claude Code plugin into the platform lock (optionally enable globally)",
  args: [
    {
      name: "ref",
      description:
        "Plugin reference: bare name (marketplace), org/repo@version, or <url>@<version>",
      required: true,
    },
  ],
  options: {
    global: {
      type: "boolean",
      short: "g",
      description: "Also add the plugin to the global plugin set",
      default: false,
    },
    plugin: {
      type: "string",
      short: "p",
      description: "When the source is a marketplace repo, select a single plugin by name",
    },
    force: {
      type: "boolean",
      short: "f",
      description: "Re-register even if the local registry already has this (name, version)",
      default: false,
    },
  },
  handler: async (parsedArgs: ParsedArgs) => {
    const ref = parsedArgs.positionals[0];
    if (!ref) {
      throw new CLIError(
        "Missing required argument: ref (example: syn claude-plugin install org/repo@v1)",
      );
    }
    const enableGlobal = parsedArgs.values["global"] === true;
    const force = parsedArgs.values["force"] === true;
    const pluginName = (parsedArgs.values["plugin"] as string | undefined) ?? null;

    // Local-cache short-circuit. We only know (name, version) up-front for
    // the parseable ref forms; bare names and marketplace repos resolve
    // their canonical name later, so the cache check happens after a
    // successful resolution as well (post-register dedup is harmless).
    // Cache key uses the canonical plugin name: when --plugin is provided,
    // that explicit name; otherwise the parsed ref's basename. The original
    // pre-fix only ran when --plugin was absent, which meant marketplace
    // installs always missed the cache (parsed ref name = repo name, but
    // recorded name = plugin's plugin.json name).
    if (!force && !isBarePluginName(ref)) {
      try {
        const parsedRef = parseClaudePluginRef(ref);
        const cacheName = pluginName ?? parsedRef.name;
        const cached = findInstalled(cacheName, parsedRef.version);
        if (cached) {
          const shortSha = cached.resolved_sha.slice(0, 12);
          printSuccess(
            `${cacheName}@${parsedRef.version} already installed (sha: ${shortSha}...). Use --force to re-register.`,
          );
          return;
        }
      } catch {
        // Unparseable ref - fall through to the resolver, which will surface
        // a real error.
      }
    }

    let ctx: InstallContext;
    if (isBarePluginName(ref)) {
      const bare = await runBareNameInstall(ref, null);
      if (bare === null) {
        throw new CLIError(
          `'${ref}' is not a known marketplace plugin. Add a registry with 'syn marketplace add', or pass a full ref like org/repo@version.`,
        );
      }
      ctx = bare;
    } else {
      ctx = await runRefInstall(ref, pluginName);
    }

    const shortSha = ctx.result.sha256.slice(0, 12);
    printSuccess(
      `Registered ${style(`${ctx.result.name}@${ctx.result.version}`, BOLD)} (sha: ${shortSha}...)`,
    );

    recordInstallation({
      name: ctx.result.name,
      version: ctx.result.version,
      source_url: ctx.sourceUrl,
      resolved_sha: ctx.result.sha256,
      marketplace_source: ctx.marketplaceSource,
    });

    if (enableGlobal) {
      await addToGlobal(ctx.result.name, ctx.result.version);
      print(`Added ${ctx.result.name} to global plugin set.`);
    } else {
      printDim(
        `  Tip: enable globally with 'syn claude-plugin global add ${ctx.result.name} ${ctx.result.version}'`,
      );
    }
  },
};
