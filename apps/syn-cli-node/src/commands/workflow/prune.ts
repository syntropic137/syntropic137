/**
 * Archiving workflows that a package no longer declares (issues #822, #1588).
 *
 * Shared by `install`, `update` and `uninstall`. All three ask the same
 * question - "of these workflows I think belong to the package, which may I
 * archive, and what happened to each" - so the answer lives here once.
 *
 * WHY the server decides ownership (issue #1588): the candidate list comes
 * from local CLI history (~/.syntropic137/workflows/installed.json), which is
 * per-machine, goes stale, and is keyed by a package name derived from a
 * directory. A collision between `implement` and `implement-v3` was enough to
 * send DELETE for `sdlc-implement-v3`, the workflow every orchestrator
 * dispatches. Local history may nominate a workflow; only the server's
 * `package_name` on that workflow can confirm it.
 */

import readline from "node:readline/promises";
import type { OptionDef, ParsedArgs } from "../../framework/command.js";
import type { InstallationRecord, InstalledWorkflowRef } from "../../packages/models.js";
import { api } from "../../client/typed.js";
import { CLIError } from "../../framework/errors.js";
import { loadInstalled } from "../../packages/resolver.js";
import { print, printDim, printWarning } from "../../output/console.js";
import { style, BOLD, DIM, GREEN, RED, YELLOW } from "../../output/ansi.js";

/**
 * Outcome of a prune.
 *
 * WHY three buckets and not a count: each one needs a different thing done
 * to the local registry. `archived` is gone. `retained` is still this
 * package's and still live - not asked for, declined, or refused because it
 * has active executions - so it stays tracked for the next run. `failed` is
 * also still live but is an error the caller must report. A workflow the
 * server attributes to another package, or to none, is in no bucket: it is
 * not this package's, so it is neither archived nor tracked under it.
 */
export interface PruneResult {
  archived: InstalledWorkflowRef[];
  retained: InstalledWorkflowRef[];
  failed: InstalledWorkflowRef[];
}

export interface PruneOptions {
  /** Package the candidates are believed to belong to. */
  packageName: string;
  /**
   * The caller asked to archive (`--prune`, or `uninstall` itself). Without
   * it the archivable workflows are listed and left alone.
   */
  prune: boolean;
  /** Skip the confirmation prompt (`--yes`). */
  yes: boolean;
}

/** The `--prune` / `--yes` flags `install` and `update` both declare. */
export const PRUNE_OPTIONS: Record<"prune" | "yes", OptionDef> = {
  prune: {
    type: "boolean",
    description: "Archive workflows this package installed but no longer declares",
    default: false,
  },
  yes: { type: "boolean", short: "y", description: "Archive without asking (with --prune)", default: false },
};

export function pruneFlags(parsed: ParsedArgs): Pick<PruneOptions, "prune" | "yes"> {
  return { prune: parsed.values["prune"] === true, yes: parsed.values["yes"] === true };
}

export function findInstallation(name: string): InstallationRecord | null {
  const registry = loadInstalled();
  for (const record of registry.installations) {
    if (record.package_name === name) return record;
  }
  return null;
}

/**
 * Archive the candidates the server confirms belong to `packageName`.
 *
 * Throws CLIError, before archiving anything, when asked to prune without
 * `--yes` and there is no terminal to ask on.
 */
export async function pruneWorkflows(
  candidates: InstalledWorkflowRef[],
  options: PruneOptions,
): Promise<PruneResult> {
  const result: PruneResult = { archived: [], retained: [], failed: [] };
  const owned = await ownedByPackage(candidates, options.packageName, result);
  if (owned.length === 0) return result;

  print(`\n${style(`Workflows ${options.packageName} no longer declares:`, BOLD)}`);
  for (const wfRef of owned) print(`  ${wfRef.name} ${style(`(${wfRef.id})`, DIM)}`);

  if (!options.prune) {
    printDim("  Left in place. Re-run with --prune to archive them.");
    result.retained.push(...owned);
    return result;
  }
  if (!options.yes && !(await confirmArchive(owned.length))) {
    printDim("  Not archived.");
    result.retained.push(...owned);
    return result;
  }

  for (const wfRef of owned) {
    await archiveOne(wfRef, result);
  }
  return result;
}

/**
 * The candidates whose server record names `packageName` as their installer.
 *
 * Everything else is reported and dropped, except a lookup that failed for a
 * reason other than "not found": that one is still possibly live and still
 * possibly ours, so it is retained rather than forgotten.
 */
async function ownedByPackage(
  candidates: InstalledWorkflowRef[],
  packageName: string,
  result: PruneResult,
): Promise<InstalledWorkflowRef[]> {
  const owned: InstalledWorkflowRef[] = [];
  for (const wfRef of candidates) {
    const { data, response } = await api.GET("/workflows/{workflow_id}", {
      params: { path: { workflow_id: wfRef.id } },
    });
    if (response.status === 404) continue;
    if (!response.ok || data === undefined) {
      printWarning(`Could not look up ${wfRef.name} (${response.status}); leaving it in place.`);
      result.retained.push(wfRef);
      continue;
    }
    if (data.package_name === packageName) {
      owned.push(wfRef);
      continue;
    }
    const owner = data.package_name ? `package '${data.package_name}'` : "no package";
    printDim(
      `  Not archiving ${wfRef.name}: local history lists it under ${packageName}, ` +
        `but the server records it as installed by ${owner}.`,
    );
  }
  return owned;
}

async function confirmArchive(count: number): Promise<boolean> {
  if (process.stdin.isTTY !== true || process.stdout.isTTY !== true) {
    throw new CLIError(
      `Refusing to archive ${count} workflow(s) without confirmation: no terminal to ask on. ` +
        "Pass --yes to archive them. Nothing was archived.",
      1,
    );
  }
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  try {
    const answer = await rl.question(`Archive these ${count} workflow(s)? [y/N] `);
    return /^y(es)?$/i.test(answer.trim());
  } finally {
    rl.close();
  }
}

async function archiveOne(wfRef: InstalledWorkflowRef, result: PruneResult): Promise<void> {
  process.stdout.write(`  Archiving ${style(wfRef.name, BOLD)}... `);
  const { error, response } = await api
    .DELETE("/workflows/{workflow_id}", { params: { path: { workflow_id: wfRef.id } } })
    .catch(() => ({ error: undefined, response: null }));
  // WHY the detail is read: the API answers 409 both for "already archived"
  // and for "has active executions", and only the message tells them apart.
  const alreadyArchived = JSON.stringify(error ?? "").toLowerCase().includes("already archived");
  if (response?.ok === true) {
    print(style("done", GREEN));
    result.archived.push(wfRef);
  } else if (response?.status === 404 || alreadyArchived) {
    // Already archived is the desired end state.
    print(style("already archived", DIM));
    result.archived.push(wfRef);
  } else if (response?.status === 409) {
    // The server refuses to archive a workflow with active executions
    // (ArchiveWorkflowTemplateHandler). That is the guard working, not a
    // failure: the workflow stays live and tracked for a later prune.
    print(style("skipped: it has running executions", YELLOW));
    result.retained.push(wfRef);
  } else {
    print(style(`failed${response ? ` (${response.status})` : ""}`, RED));
    result.failed.push(wfRef);
  }
}
