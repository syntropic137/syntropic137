/** `syn workflow tag add|remove <workflow-id> <tag...>` (#967). */

import type { CommandDef, ParsedArgs } from "../../framework/command.js";
import { api, unwrap } from "../../client/typed.js";
import type { components } from "../../generated/api-types.js";
import { print, printDim } from "../../output/console.js";
import { style, GREEN } from "../../output/ansi.js";
import { parseTagEdit, printTags, tagEditArgs, type TagEdit } from "../tag-edit.js";
import { resolveWorkflow } from "./resolver.js";

type WorkflowTagsResponse = components["schemas"]["WorkflowTagsResponse"];

type TagEditResult = Awaited<ReturnType<typeof request>>;

function request(edit: TagEdit, workflowId: string) {
  const path = { workflow_id: workflowId };
  return edit.action === "add"
    ? api.POST("/workflows/{workflow_id}/tags", { params: { path }, body: { tags: edit.tags } })
    : api.DELETE("/workflows/{workflow_id}/tags", { params: { path, query: { tag: edit.tags } } });
}

function unwrapEdit(edit: TagEdit, result: TagEditResult): WorkflowTagsResponse {
  return unwrap<WorkflowTagsResponse>(result, edit.action === "add" ? "Add workflow tags" : "Remove workflow tags");
}

/**
 * Send the id as typed first. The route resolves prefixes itself and asks the
 * aggregate, so a workflow whose read model has not caught up yet is still
 * editable. Only after the authoritative 404 do we fall back to the
 * read-model resolver, for its "no match" guidance and for any match it finds
 * that the route did not.
 */
async function send(edit: TagEdit): Promise<WorkflowTagsResponse> {
  const first = await request(edit, edit.id);
  if (first.response.status !== 404) return unwrapEdit(edit, first);
  const wf = await resolveWorkflow(edit.id);
  if (wf.id === edit.id) return unwrapEdit(edit, first);
  return unwrapEdit(edit, await request(edit, wf.id));
}

export const tagCommand: CommandDef = {
  name: "tag",
  description: "Add or remove a workflow's tags. Future runs inherit them; existing runs keep their own",
  args: tagEditArgs("workflow"),
  examples: [
    "syn workflow tag add <workflow-id> team:evals nightly",
    "syn workflow tag remove <workflow-id> nightly",
  ],
  handler: async (parsed: ParsedArgs) => {
    const edit = parseTagEdit(parsed, "workflow");
    const data = await send(edit);
    print(style(`Tags of ${data.workflow_id}`, GREEN));
    printTags("tags: ", data.tags);
    printDim("Existing executions keep the tags they launched with.");
  },
};
