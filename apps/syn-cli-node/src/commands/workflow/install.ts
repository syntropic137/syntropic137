/**
 * Workflow install, installed, and init commands.
 * Port of apps/syn-cli/src/syn_cli/commands/workflow/_install.py
 */

import fs from "node:fs";
import path from "node:path";
import type { CommandDef, ParsedArgs } from "../../framework/command.js";
import { CLIError } from "../../framework/errors.js";
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
import { removeTempDir } from "../../packages/git.js";
import { resolveFromMarketplace } from "../../marketplace/client.js";
import { runClaudePluginPreflight } from "../../packages/claude-plugin-preflight.js";
import { postYaml } from "../../client/yaml-upload.js";
import { runSkillPreflight } from "../../packages/skill-preflight.js";

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
  // WHY (#726): the marketplace resolver is now artifact-agnostic; the
  // workflow-specific work (resolving the package into a list of workflows)
  // happens here, after the directory is on disk.
  const resolved = await resolveFromMarketplace(source, ref);
  if (resolved === null) return null;

  print(
    `Found ${style(resolved.entry.name, BOLD)} in marketplace ${style(resolved.registryName, CYAN)}`,
  );
  print(`Cloning ...@${resolved.resolvedRef} (already done)`);

  const { manifest, workflows } = resolvePackage(resolved.packagePath);
  return {
    packagePath: resolved.packagePath,
    manifest,
    workflows,
    tmpdir: resolved.tmpdir,
    marketplaceSource: resolved.registryName,
    gitSha: resolved.gitSha,
    effectiveRef: resolved.resolvedRef,
  };
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
      // WHY from-yaml rather than a hand-built JSON body: the old body named
      // each field explicitly, so every key it did not name was silently
      // dropped on install - `skills:` and `claude_plugins:` among them, and
      // whatever field is added next. Uploading the resolved definition lets
      // the server own every YAML semantic (ADR-058 requires_repos inference
      // included), which is what `syn workflow create --from` already does.
      //
      // workflowId preserves the stable id declared in workflow.yaml. Without
      // it the server mints a fresh uuid on every install, so `syn workflow
      // run <yaml-id>` cannot resolve and re-installing the same package
      // silently piles up duplicates.
      const data = await postYaml(Buffer.from(JSON.stringify(wf.definition), "utf-8"), {
        name: wf.name,
        workflowId: wf.id,
        contentType: "application/json",
        errorLabel: "workflow install",
      });
      const wfId = data.id;
      print(`${style("done", GREEN)} (id: ${wfId})`);
      installed.push({ id: wfId, name: wf.name });
    } catch (err) {
      print(style("failed", "\x1b[31m"));
      if (err instanceof Error) printError(err.message);
      // WHY rethrow rather than collect and continue: swallowing this left the
      // package half-installed while the command still printed
      // "Installed N workflow(s)" and recorded the install, so a user had no
      // signal that a workflow they asked for is missing. The workflows
      // created before this point still exist - install is not transactional
      // server-side - so the message says so rather than implying a clean
      // rollback.
      throw new CLIError(
        `Failed to create workflow '${wf.name}' (${i + 1} of ${workflows.length}).\n` +
          (installed.length > 0
            ? `  ${installed.length} workflow(s) were already created and remain installed: ` +
              `${installed.map((w) => w.name).join(", ")}.\n` +
              "  Fix the error and re-run to finish, or remove them with `syn workflow delete`."
            : "  No workflows were installed."),
      );
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

      // WHY (#726 Phase B): if any workflow YAML declares `claude_plugins:`,
      // resolve them BEFORE we mutate the API. This keeps install atomic
      // from the user's perspective without requiring the API to do git work.
      await runClaudePluginPreflight(packagePath);

      // WHY here: same reasoning as the claude-plugin preflight above. A
      // workflow declaring `skills:` used to install cleanly and then fail at
      // execution with SkillNotRegistered, after the user had committed to a
      // run. This also pins bundled refs in the definitions about to be
      // uploaded, so both preflights must precede installWorkflowsViaApi.
      await runSkillPreflight(packagePath, workflows);

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
// packages
// ---------------------------------------------------------------------------

export const packagesCommand: CommandDef = {
  name: "packages",
  description: "List workflow packages pulled from the marketplace (local CLI history; use 'syn workflow list' to see what is currently on the running stack)",
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
    type: { type: "string", short: "t", description: "Free-form workflow type label (e.g. research, planning, custom, code-quality)", default: "custom" },
    phases: { type: "string", description: "Number of phases", default: "3" },
    multi: { type: "boolean", description: "Scaffold multi-workflow plugin", default: false },
  },
  handler: async (parsed: ParsedArgs) => {
    const workflowType = (parsed.values["type"] as string | undefined) ?? "custom";
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
