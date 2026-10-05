/**
 * Workflow update and uninstall commands.
 * Port of apps/syn-cli/src/syn_cli/commands/workflow/_update.py
 */

import type { CommandDef, ParsedArgs } from "../../framework/command.js";
import { CLIError } from "../../framework/errors.js";
import { printError, printSuccess, print, printDim } from "../../output/console.js";
import { style, BOLD, CYAN } from "../../output/ansi.js";
import type { InstallationRecord, PluginManifest, ResolvedWorkflow } from "../../packages/models.js";
import {
  detectFormat,
  loadInstalled,
  recordInstallation,
  saveInstalled,
} from "../../packages/resolver.js";
import { removeTempDir } from "../../packages/git.js";
import { resolvePluginByName, getRemoteRefSha } from "../../marketplace/client.js";
import {
  isBarePluginName,
  tryMarketplaceResolution,
  resolveSource,
  installWorkflowsViaApi,
} from "./install.js";
import { findInstallation, pruneWorkflows, PRUNE_OPTIONS, pruneFlags } from "./prune.js";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------


function removeInstallation(name: string): void {
  const registry = loadInstalled();
  const remaining = registry.installations.filter((r) => r.package_name !== name);
  saveInstalled({ version: registry.version, installations: remaining });
}


async function isAlreadyUpToDate(
  record: InstallationRecord,
  effectiveRef: string,
): Promise<boolean> {
  if (!record.marketplace_source || !record.git_sha) return false;

  const result = await resolvePluginByName(record.package_name, record.marketplace_source);
  if (result === null) return false;

  const [_regName, entry, _plugin] = result;
  const currentSha = await getRemoteRefSha(entry.repo, effectiveRef);
  return currentSha !== null && currentSha === record.git_sha;
}

// ---------------------------------------------------------------------------
// update
// ---------------------------------------------------------------------------

export const updateCommand: CommandDef = {
  name: "update",
  description: "Update an installed workflow package to the latest version",
  args: [{ name: "name", description: "Package name to update", required: true }],
  options: {
    ref: { type: "string", description: "Override git ref" },
    "dry-run": { type: "boolean", short: "n", description: "Check for updates without applying", default: false },
    force: {
      type: "boolean",
      description: "Reinstall even if the resolved version is already installed",
      default: false,
    },
    ...PRUNE_OPTIONS,
  },
  handler: async (parsed: ParsedArgs) => {
    const name = parsed.positionals[0];
    if (!name) {
      printError("Missing required argument: name");
      throw new CLIError("Missing argument", 1);
    }

    const force = parsed.values["force"] === true;

    const record = findInstallation(name);
    if (record === null) {
      printError(`Package '${name}' is not installed`);
      printDim("See installed packages: syn workflow installed");
      throw new CLIError("Not installed", 1);
    }

    const source = record.source;
    const effectiveRef = (parsed.values["ref"] as string | undefined) ?? record.source_ref;
    const dryRun = parsed.values["dry-run"] === true;

    // WHY force short-circuits this (issue #822): the up-to-date check
    // returned before force was considered, so --force did nothing in the
    // exact case someone reaches for it - the sha has not moved and they want
    // to reinstall anyway.
    if (!force && (await isAlreadyUpToDate(record, effectiveRef))) {
      printDim(`Package '${name}' is already up to date`);
      return;
    }

    if (dryRun) {
      print(`${style("Update available", CYAN)} for ${style(name, BOLD)}`);
      print(`  Source: ${source}`);
      print(`  Ref: ${effectiveRef}`);
      printDim("Run without --dry-run to apply");
      return;
    }

    // Resolve updated source
    let packagePath: string;
    let manifest: PluginManifest | null;
    let workflows: ResolvedWorkflow[];
    let tmpdir: string | null = null;
    let marketplaceSource: string | null = null;
    let gitSha: string | null = null;
    let resolvedRef = effectiveRef;

    try {
      if (isBarePluginName(source) && record.marketplace_source) {
        const mktResult = await tryMarketplaceResolution(source, effectiveRef);
        if (mktResult !== null) {
          ({ packagePath, manifest, workflows, tmpdir, marketplaceSource, gitSha, effectiveRef: resolvedRef } = mktResult);
        } else {
          printError(`Plugin '${name}' no longer found in marketplace`);
          throw new CLIError("Not found", 1);
        }
      } else {
        ({ packagePath, manifest, workflows, tmpdir, gitSha } = await resolveSource(
          source,
          effectiveRef,
        ));
      }
    } catch (err) {
      if (err instanceof CLIError) throw err;
      printError(err instanceof Error ? err.message : String(err));
      throw new CLIError("Resolution failed", 1);
    }

    try {
      if (workflows.length === 0) {
        printError("No workflows found in updated package");
        throw new CLIError("No workflows", 1);
      }

      const fmt = detectFormat(packagePath);
      const pkgName = manifest?.name ?? name;
      const pkgVersion = manifest?.version ?? "0.0.0";

      // Preview
      print("");
      print(style("Package Preview", CYAN));
      print(`  ${style(`${pkgName} v${pkgVersion}`, BOLD)}`);
      print(`  Source: ${source}`);
      print(`  Format: ${fmt}`);
      print(`  Workflows: ${workflows.length}`);

      // WHY this order (issue #822): update used to archive every old
      // workflow and drop the registry record BEFORE creating the
      // replacements. Any failure in the create step - a 409, a validation
      // error, a half-installed multi-workflow package - left the user with
      // nothing and no record to recover from. Archive is a soft delete, so
      // the ids were not even reusable. That is data loss, and it is the
      // command a user reaches for after an install fails.
      //
      // Install is an upsert now, so the replacements can be written first.
      // Only workflows the package no longer declares are archived, and only
      // once every upsert has succeeded.
      print(`\n${style("Installing updated workflows...", BOLD)}`);
      const installedRefs = await installWorkflowsViaApi(workflows, {
        version: pkgVersion,
        sourceDigest: gitSha,
        force,
        packageName: pkgName,
      });

      if (installedRefs.length === 0) {
        printError("No workflows were installed during update");
        throw new CLIError("Update failed", 1);
      }

      // Workflows that existed before but are gone from this version. Runs
      // only after every upsert above succeeded; local history nominates,
      // the server's provenance decides, --prune archives (issue #1588).
      const installedIds = new Set(installedRefs.map((w) => w.id));
      const prune = await pruneWorkflows(
        record.workflows.filter((w) => !installedIds.has(w.id)),
        { packageName: pkgName, ...pruneFlags(parsed) },
      );

      // WHY retained and failed refs stay in the record (issue #822): a
      // workflow still live on the server must stay tracked locally.
      recordInstallation({
        packageName: pkgName,
        packageVersion: pkgVersion,
        source,
        sourceRef: resolvedRef,
        format: fmt,
        workflows: [...installedRefs, ...prune.retained, ...prune.failed],
        marketplaceSource: marketplaceSource ?? record.marketplace_source ?? null,
        gitSha: gitSha ?? record.git_sha ?? null,
      });

      if (prune.failed.length > 0) {
        printError(
          `Updated, but ${prune.failed.length} old workflow(s) could not be archived. ` +
            "They remain active and are still tracked. Re-run with `syn workflow update --force --prune` (a plain re-run can short-circuit as already up to date), or " +
            "remove them with `syn workflow delete`.",
        );
        throw new CLIError("Partial update", 1);
      }

      printSuccess(`\nUpdated ${pkgName} (${installedRefs.length} workflow(s))`);
    } finally {
      if (tmpdir !== null) {
        removeTempDir(tmpdir);
      }
    }
  },
};

// ---------------------------------------------------------------------------
// uninstall
// ---------------------------------------------------------------------------

export const uninstallCommand: CommandDef = {
  name: "uninstall",
  description: "Uninstall a workflow package",
  args: [{ name: "name", description: "Package name to uninstall", required: true }],
  options: {
    "keep-workflows": { type: "boolean", description: "Remove from registry but keep workflows in the platform", default: false },
  },
  handler: async (parsed: ParsedArgs) => {
    const name = parsed.positionals[0];
    if (!name) {
      printError("Missing required argument: name");
      throw new CLIError("Missing argument", 1);
    }

    const record = findInstallation(name);
    if (record === null) {
      printError(`Package '${name}' is not installed`);
      printDim("See installed packages: syn workflow installed");
      throw new CLIError("Not installed", 1);
    }

    if (parsed.values["keep-workflows"] !== true) {
      print(`Removing workflows from ${style(name, BOLD)}...`);
      // Uninstall is itself the confirmed request to archive; ownership is
      // still the server's call (issue #1588).
      const prune = await pruneWorkflows(record.workflows, {
        packageName: name,
        prune: true,
        yes: true,
      });
      print(`  Removed ${prune.archived.length} workflow(s)`);
      // WHY this stops rather than dropping the record (issue #822): removing
      // the registry entry while a workflow is still live on the server
      // orphans it, with no local record naming it any more.
      const stillLive = [...prune.retained, ...prune.failed];
      if (stillLive.length > 0) {
        printError(
          `${stillLive.length} workflow(s) were not archived and are still active: ` +
            `${stillLive.map((w) => w.name).join(", ")}. ` +
            "The package remains installed. Re-run uninstall once they can be archived.",
        );
        throw new CLIError("Partial uninstall", 1);
      }
    }

    removeInstallation(name);
    printSuccess(`Uninstalled ${style(name, BOLD)}`);
  },
};
