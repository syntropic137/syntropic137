/** `syn workflow tag add|remove <workflow-id> <tag...>` (#967). */

import type { CommandDef, ParsedArgs } from "../../framework/command.js";
import { api, unwrap } from "../../client/typed.js";
import type { components } from "../../generated/api-types.js";
import { print, printDim } from "../../output/console.js";
import { style, GREEN } from "../../output/ansi.js";
import { parseTagEdit, printTags, tagEditArgs, type TagEdit } from "../tag-edit.js";
import { resolveWorkflow } from "./resolver.js";

type WorkflowTagsResponse = components["schemas"]["WorkflowTagsResponse"];

async function send(edit: TagEdit, workflowId: string): Promise<WorkflowTagsResponse> {
  const path = { workflow_id: workflowId };
  if (edit.action === "add") {
    return unwrap<WorkflowTagsResponse>(
      await api.POST("/workflows/{workflow_id}/tags", { params: { path }, body: { tags: edit.tags } }),
      "Add workflow tags",
    );
  }
  return unwrap<WorkflowTagsResponse>(
    await api.DELETE("/workflows/{workflow_id}/tags", { params: { path, query: { tag: edit.tags } } }),
    "Remove workflow tags",
  );
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
    // Same id resolution as `workflow show`: an exact id, a prefix, or a name.
    const wf = await resolveWorkflow(edit.id);
    const data = await send(edit, wf.id);
    print(style(`Tags of ${data.workflow_id}`, GREEN));
    printTags("tags: ", data.tags);
    printDim("Existing executions keep the tags they launched with.");
  },
};
