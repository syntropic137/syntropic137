/**
 * Workflow install, installed, and init commands.
 * Port of apps/syn-cli/src/syn_cli/commands/workflow/_install.py
 */

import fs from "node:fs";
import path from "node:path";
import type { CommandDef, ParsedArgs } from "../../framework/command.js";
import { CLIError } from "../../framework/errors.js";
import { api, unwrap } from "../../client/typed.js";
import { printError, printSuccess, print, printDim } from "../../output/console.js";
import { style, BOLD, CYAN, DIM, GREEN } from "../../output/ansi.js";
import { formatTimestamp } from "../../output/format.js";
import { Table } from "../../output/table.js";
import type { InstalledWorkflowRef, PackageFormat, PluginManifest, ResolvedWorkflow } from "../../packages/models.js";
import {
  detectFormat,
  loadInstalled,
  parseSource,
  recordInstallation,
  resolveFromGit,
  resolvePackage,
  scaffoldSinglePackage,
  scaffoldMultiPackage,
} from "../../packages/resolver.js";
import { gitClone, makeTempDir, removeTempDir } from "../../packages/git.js";
import { resolvePluginByName, getGitHeadSha } from "../../marketplace/client.js";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

export function isBarePluginName(source: string): boolean {
  return (
    !source.includes("/") &&
    !source.startsWith(".") &&
    !source.startsWith("http") &&
    !source.startsWith("git@") &&
    !source.startsWith("ssh://") &&
    !fs.existsSync(source)
  );
}

export async function tryMarketplaceResolution(
  source: string,
  ref: string,
): Promise<{
  packagePath: string;
  manifest: PluginManifest | null;
  workflows: ResolvedWorkflow[];
  tmpdir: string | null;
  marketplaceSource: string | null;
  gitSha: string | null;
  effectiveRef: string;
} | null> {
  const result = await resolvePluginByName(source);
  if (result === null) return null;

  const [regName, entry, plugin] = result;
  const effectiveRef = ref !== "main" ? ref : entry.ref;
  const url = `https://github.com/${entry.repo}.git`;

  // Validate plugin source path
  if (plugin.source.startsWith("/") || plugin.source.includes("..")) {
    throw new Error(`Unsafe plugin source path in marketplace: ${plugin.source}`);
  }

  print(`Found ${style(plugin.name, BOLD)} in marketplace ${style(regName, CYAN)}`);
  print(`Cloning ${style(entry.repo, CYAN)}@${effectiveRef}...`);

  // Clone only — don't resolve at repo root (marketplace root != plugin root)
  const tmpdir = makeTempDir("syn-pkg-");
  try {
    await gitClone(url, effectiveRef, tmpdir);
  } catch (err) {
    removeTempDir(tmpdir);
    throw err;
  }

  // Resolve from plugin's subdirectory
  const subdir = path.resolve(tmpdir, plugin.source.replace(/^\.\//, ""));
  if (!subdir.startsWith(tmpdir)) {
    removeTempDir(tmpdir);
    throw new Error(`Plugin source path escapes repository: ${plugin.source}`);
  }

  const { manifest, workflows } = resolvePackage(subdir);
  const gitSha = await getGitHeadSha(entry.repo, effectiveRef);

  return { packagePath: subdir, manifest, workflows, tmpdir, marketplaceSource: regName, gitSha, effectiveRef };
}

export async function resolveSource(
  source: string,
  ref: string,
): Promise<{
  packagePath: string;
  manifest: PluginManifest | null;
  workflows: ResolvedWorkflow[];
  tmpdir: string | null;
}> {
  const { resolved, isRemote } = parseSource(source);

  if (isRemote) {
    print(`Cloning ${style(resolved, CYAN)}@${ref}...`);
    const { tmpdir, manifest, workflows } = await resolveFromGit(resolved, ref);
    return { packagePath: tmpdir, manifest, workflows, tmpdir };
  }

  const packagePath = path.resolve(resolved);
  const { manifest, workflows } = resolvePackage(packagePath);
  return { packagePath, manifest, workflows, tmpdir: null };
}

export async function installWorkflowsViaApi(
  workflows: ResolvedWorkflow[],
): Promise<InstalledWorkflowRef[]> {
  const installed: InstalledWorkflowRef[] = [];
  for (let i = 0; i < workflows.length; i++) {
    const wf = workflows[i]!;
    process.stdout.write(`  [${i + 1}/${workflows.length}] Creating ${style(wf.name, BOLD)}... `);
    try {
      const data = unwrap(
        await api.POST("/workflows", {
          body: {
            name: wf.name,
            workflow_type: wf.workflow_type,
            classification: wf.classification ?? "standard",
            repository_url: wf.repository_url,
            repository_ref: wf.repository_ref,
            description: wf.description ?? null,
            project_name: wf.project_name ?? null,
            phases: wf.phases,
            input_declarations: wf.input_declarations,
          },
        }),
        "Failed to create workflow",
      );
      const wfId = data.id;
      print(`${style("done", GREEN)} (id: ${wfId})`);
      installed.push({ id: wfId, name: wf.name });
    } catch (err) {
      print(style("failed", "\x1b[31m"));
      if (err instanceof Error) printError(err.message);
    }
  }
  return installed;
}

// ---------------------------------------------------------------------------
// install
// ---------------------------------------------------------------------------

export const installCommand: CommandDef = {
  name: "install",
  description: "Install workflow(s) from a package, git repository, or marketplace",
  args: [{ name: "source", description: "Plugin name, local path, GitHub URL, or org/repo shorthand", required: true }],
  options: {
    ref: { type: "string", description: "Git branch/tag to clone", default: "main" },
    "dry-run": { type: "boolean", short: "n", description: "Validate without installing", default: false },
  },
  handler: async (parsed: ParsedArgs) => {
    const source = parsed.positionals[0];
    if (!source) {
      printError("Missing required argument: source");
      throw new CLIError("Missing argument", 1);
    }

    const ref = (parsed.values["ref"] as string | undefined) ?? "main";
    const dryRun = parsed.values["dry-run"] === true;

    // Try marketplace first for bare names
    let packagePath: string;
    let manifest: PluginManifest | null;
    let workflows: ResolvedWorkflow[];
    let tmpdir: string | null = null;
    let marketplaceSource: string | null = null;
    let gitSha: string | null = null;
    let effectiveRef = ref;

    try {
      if (isBarePluginName(source)) {
        const mktResult = await tryMarketplaceResolution(source, ref);
        if (mktResult !== null) {
          ({ packagePath, manifest, workflows, tmpdir, marketplaceSource, gitSha, effectiveRef } = mktResult);
        } else {
          ({ packagePath, manifest, workflows, tmpdir } = await resolveSource(source, ref));
        }
      } else {
        ({ packagePath, manifest, workflows, tmpdir } = await resolveSource(source, ref));
      }
    } catch (err) {
      printError(err instanceof Error ? err.message : String(err));
      throw new CLIError("Resolution failed", 1);
    }

    try {
      if (workflows.length === 0) {
        printError("No workflows found in package");
        throw new CLIError("No workflows", 1);
      }

      const fmt = detectFormat(packagePath);
      const pkgName = manifest?.name ?? path.basename(packagePath);
      const pkgVersion = manifest?.version ?? "0.0.0";

      printPackagePreview(pkgName, pkgVersion, source, fmt, workflows);

      if (dryRun) {
        printSuccess("Dry run — package is valid, no workflows installed");
        printWorkflowSummary(workflows);
        return;
      }

      const installedRefs = await installWorkflowsViaApi(workflows);

      if (installedRefs.length === 0) {
        printError("No workflows were installed");
        throw new CLIError("Install failed", 1);
      }

      recordInstallation({
        packageName: pkgName,
        packageVersion: pkgVersion,
        source,
        sourceRef: effectiveRef,
        format: fmt,
        workflows: installedRefs,
        marketplaceSource,
        gitSha,
      });

      printSuccess(`\nInstalled ${installedRefs.length} workflow(s) from ${source}`);
    } finally {
      if (tmpdir !== null) {
        removeTempDir(tmpdir);
      }
    }
  },
};

function printPackagePreview(
  name: string,
  version: string,
  source: string,
  fmt: PackageFormat,
  workflows: ResolvedWorkflow[],
): void {
  const totalPhases = workflows.reduce((sum, wf) => sum + wf.phases.length, 0);
  print("");
  print(style("Package Preview", CYAN));
  print(`  ${style(`${name} v${version}`, BOLD)}`);
  print(`  Source: ${source}`);
  print(`  Format: ${fmt}`);
  print(`  Workflows: ${workflows.length}`);
  print(`  Total phases: ${totalPhases}`);
}

function printWorkflowSummary(workflows: ResolvedWorkflow[]): void {
  const table = new Table({ title: "Resolved Workflows" });
  table.addColumn("Name", { style: CYAN });
  table.addColumn("ID", { style: DIM });
  table.addColumn("Type");
  table.addColumn("Phases", { align: "right" });

  for (const wf of workflows) {
    table.addRow(wf.name, wf.id, wf.workflow_type, String(wf.phases.length));
  }
  table.print();
}

// ---------------------------------------------------------------------------
// installed
// ---------------------------------------------------------------------------

export const installedCommand: CommandDef = {
  name: "installed",
  description: "List installed workflow packages",
  handler: async () => {
    const registry = loadInstalled();

    // Filter out entries whose local source path no longer exists.
    // Remote sources (URLs, git@, GitHub shorthand, marketplace bare names) are always shown.
    const liveInstallations = registry.installations.filter((r) => {
      const src = r.source;
      const isGitHubShorthand = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+(?:#.+)?$/.test(src);
      const isRemote = src.includes("://") || src.startsWith("git@") || src.startsWith("ssh://") || isBarePluginName(src) || isGitHubShorthand;
      if (isRemote) return true;
      return fs.existsSync(path.resolve(src));
    });

    if (liveInstallations.length === 0) {
      printDim("No packages installed yet.");
      print(`Install one with: ${style("syn workflow install <source>", CYAN)}`);
      return;
    }

    const table = new Table({ title: "Installed Packages" });
    table.addColumn("Package", { style: CYAN });
    table.addColumn("Version");
    table.addColumn("Source", { style: DIM });
    table.addColumn("Workflows", { align: "right" });
    table.addColumn("Installed", { style: DIM });

    for (const record of liveInstallations) {
      table.addRow(
        record.package_name,
        record.package_version,
        record.source,
        String(record.workflows.length),
        formatTimestamp(record.installed_at),
      );
    }
    table.print();
  },
};

// ---------------------------------------------------------------------------
// init
// ---------------------------------------------------------------------------

export const initCommand: CommandDef = {
  name: "init",
  description: "Scaffold a new workflow package from a template",
  args: [{ name: "directory", description: "Directory to scaffold (defaults to current dir)" }],
  options: {
    name: { type: "string", short: "n", description: "Workflow name" },
    type: { type: "string", short: "t", description: "Workflow type", default: "research" },
    phases: { type: "string", description: "Number of phases", default: "3" },
    multi: { type: "boolean", description: "Scaffold multi-workflow plugin", default: false },
  },
  handler: async (parsed: ParsedArgs) => {
    const workflowType = (parsed.values["type"] as string | undefined) ?? "research";
    const numPhases = parseInt((parsed.values["phases"] as string | undefined) ?? "3", 10);
    const multi = parsed.values["multi"] === true;
    const explicitName = parsed.values["name"] as string | undefined;

    // When no directory is given, default to a new named subdirectory in cwd
    // (not cwd itself — cwd is almost always non-empty in a project).
    const defaultDir = explicitName
      ? path.basename(explicitName.toLowerCase().replace(/\s+/g, "-")) || "my-workflow"
      : "my-workflow";
    const directory = parsed.positionals[0] ?? defaultDir;
    const resolvedDir = path.resolve(directory);

    const wfName = explicitName ??
      path.basename(resolvedDir).replace(/[-_]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

    if (fs.existsSync(resolvedDir)) {
      const entries = fs.readdirSync(resolvedDir);
      if (entries.length > 0) {
        printError(`Directory is not empty: ${resolvedDir}`);
        throw new CLIError("Directory not empty", 1);
      }
    }

    if (multi) {
      scaffoldMultiPackage(resolvedDir, { name: wfName, workflowType, numPhases });
    } else {
      scaffoldSinglePackage(resolvedDir, { name: wfName, workflowType, numPhases });
    }

    const fmtLabel = multi ? "multi-workflow plugin" : "single workflow package";
    printSuccess(`Scaffolded ${fmtLabel} at ${resolvedDir}`);
    print("\nNext steps:");
    print(`  1. Edit the prompts in ${style(`${resolvedDir}/phases/`, CYAN)}`);
    print(`  2. Validate: ${style(`syn workflow validate ${resolvedDir}`, CYAN)}`);
    print(`  3. Install: ${style(`syn workflow install ${resolvedDir}`, CYAN)}`);
  },
};
