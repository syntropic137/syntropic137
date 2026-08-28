/**
 * Workflow ID resolution with partial matching.
 * Port of apps/syn-cli/src/syn_cli/commands/_workflow_resolver.py
 */

import { CLIError } from "../../framework/errors.js";
import { api, unwrap } from "../../client/typed.js";
import { printError, print, printDim } from "../../output/console.js";
import { style, YELLOW, DIM as DIM_CODE } from "../../output/ansi.js";
import type { WorkflowSummary } from "./models.js";

/**
 * WHY 100 (issue #880): the API caps page_size at 100, so this is the
 * fewest round trips it will allow. The previous code took the default page
 * of 20 and matched client-side, so on a stack with more than 20 workflows
 * anything past the first page reported "No workflow found matching" - the
 * one message guaranteed to send a user off reinstalling something that was
 * already installed correctly.
 */
const PAGE_SIZE = 100;

/**
 * Pages the workflow list to exhaustion.
 *
 * A partial match genuinely needs every workflow, so a single page is not a
 * shortcut, it is a wrong answer that looks like a right one.
 */
async function listAllWorkflows(includeArchived: boolean): Promise<WorkflowSummary[]> {
  const all: WorkflowSummary[] = [];
  for (let page = 1; ; page++) {
    const data = unwrap(
      await api.GET("/workflows", {
        params: {
          query: { include_archived: includeArchived, page, page_size: PAGE_SIZE },
        },
      }),
      "Failed to list workflows",
    );
    const batch = data.workflows ?? [];
    all.push(
      ...batch.map((w) => ({
        id: w.id,
        name: w.name,
        workflow_type: w.workflow_type,
        phase_count: w.phase_count ?? 0,
      })),
    );
    // A short page is the last page. Stopping on an empty page instead would
    // cost one extra request on every exact-multiple boundary.
    if (batch.length < PAGE_SIZE) return all;
  }
}

export async function resolveWorkflow(
  partialId: string,
  opts?: { includeArchived?: boolean },
): Promise<WorkflowSummary> {
  // WHY the detail endpoint first (issue #880): GET /workflows/{id} is the
  // authoritative lookup and is not paginated. An exact id - which is what
  // every install prints and every script passes - resolves in one request
  // and cannot be hidden by a page boundary.
  const exact = await api.GET("/workflows/{workflow_id}", {
    params: { path: { workflow_id: partialId } },
  });
  // Require an actual id rather than trusting any 2xx: a body without one is
  // not a workflow, and treating it as a hit would return an object whose
  // every field is undefined.
  if (exact.error === undefined && typeof exact.data?.id === "string") {
    return {
      id: exact.data.id,
      name: exact.data.name,
      workflow_type: exact.data.workflow_type,
      phase_count: exact.data.phases?.length ?? 0,
    };
  }

  const workflows = await listAllWorkflows(opts?.includeArchived ?? false);
  const matching = workflows.filter((w) => w.id.startsWith(partialId));

  if (matching.length === 0) {
    printError(`No workflow found matching: ${partialId}`);
    printDim(`Searched ${workflows.length} workflow(s). List them with: syn workflow list`);
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

  return matching[0]!;
}
