/**
 * Workflow ID resolution with partial matching.
 * Port of apps/syn-cli/src/syn_cli/commands/_workflow_resolver.py
 */

import { CLIError } from "../../framework/errors.js";
import { api, unwrap } from "../../client/typed.js";
import { printError, print, printDim } from "../../output/console.js";
import { style, YELLOW, DIM as DIM_CODE } from "../../output/ansi.js";
import type { WorkflowSummary } from "./models.js";

export async function resolveWorkflow(
  partialId: string,
  opts?: { includeArchived?: boolean },
): Promise<WorkflowSummary> {
  const data = unwrap(
    await api.GET("/workflows", {
      params: { query: { include_archived: opts?.includeArchived ?? false } },
    }),
    "Failed to list workflows",
  );
  const workflows = data.workflows ?? [];
  const matching = workflows.filter((w) => w.id.startsWith(partialId));

  if (matching.length === 0) {
    printError(`No workflow found matching: ${partialId}`);
    throw new CLIError("Workflow not found", 1);
  }

  if (matching.length > 1) {
    print(style(`Multiple workflows match '${partialId}':`, YELLOW));
    for (const w of matching.slice(0, 5)) {
      print(`  ${style(w.id.slice(0, 12) + "...", DIM_CODE)} - ${w.name}`);
    }
    printDim("Please provide a more specific ID");
    throw new CLIError("Ambiguous workflow ID", 1);
  }

  const m = matching[0]!;
  return {
    id: m.id,
    name: m.name,
    workflow_type: m.workflow_type,
    phase_count: m.phase_count ?? 0,
  };
}
