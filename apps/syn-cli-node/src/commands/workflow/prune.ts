/**
 * Archiving workflows that a package no longer declares (issue #822).
 *
 * Shared by `install` and `update`. Both now upsert first and archive after,
 * so both need the same answer to "what happened to each workflow I tried to
 * remove", and both must refuse to drop a ref from the registry while the
 * workflow is still live on the server.
 */

import type { InstallationRecord, InstalledWorkflowRef } from "../../packages/models.js";
import { api, unwrap } from "../../client/typed.js";
import { CLIError } from "../../framework/errors.js";
import { loadInstalled } from "../../packages/resolver.js";
import { print } from "../../output/console.js";
import { style, BOLD, DIM, GREEN, RED } from "../../output/ansi.js";

/**
 * Outcome of an archive sweep.
 *
 * WHY structured rather than a count: an already-archived workflow and one
 * whose DELETE failed are not the same thing. Treating them alike means
 * either false alarms on the benign case or, worse, reporting success while a
 * workflow stays live on the server and vanishes from the registry.
 */
export interface PruneResult {
  gone: InstalledWorkflowRef[];
  failed: InstalledWorkflowRef[];
}

export function findInstallation(name: string): InstallationRecord | null {
  const registry = loadInstalled();
  for (const record of registry.installations) {
    if (record.package_name === name) return record;
  }
  return null;
}

export async function pruneWorkflows(refs: InstalledWorkflowRef[]): Promise<PruneResult> {
  const gone: InstalledWorkflowRef[] = [];
  const failed: InstalledWorkflowRef[] = [];
  for (const wfRef of refs) {
    process.stdout.write(`  Removing ${style(wfRef.name, BOLD)}... `);
    try {
      unwrap(
        await api.DELETE("/workflows/{workflow_id}", {
          params: { path: { workflow_id: wfRef.id } },
        }),
        "Failed to delete workflow",
      );
      print(style("done", GREEN));
      gone.push(wfRef);
    } catch (err) {
      const msg = err instanceof CLIError ? err.message.toLowerCase() : "";
      const isGone = msg.includes("already archived") || msg.includes("not found");
      print(isGone ? style("already archived", DIM) : style("failed", RED));
      // Already archived is the desired end state, so it counts as gone.
      (isGone ? gone : failed).push(wfRef);
    }
  }
  return { gone, failed };
}
