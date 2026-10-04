/** `syn execution tag add|remove <execution-id> <tag...>` (#967). */

import type { CommandDef, ParsedArgs } from "../framework/command.js";
import { api, unwrap } from "../client/typed.js";
import type { components } from "../generated/api-types.js";
import { print } from "../output/console.js";
import { style, GREEN } from "../output/ansi.js";
import { parseTagEdit, printTags, tagEditArgs, type TagEdit } from "./tag-edit.js";

type ExecutionTagsResponse = components["schemas"]["ExecutionTagsResponse"];

async function send(edit: TagEdit): Promise<ExecutionTagsResponse> {
  const path = { execution_id: edit.id };
  if (edit.action === "add") {
    return unwrap<ExecutionTagsResponse>(
      await api.POST("/executions/{execution_id}/tags", { params: { path }, body: { tags: edit.tags } }),
      "Add execution tags",
    );
  }
  return unwrap<ExecutionTagsResponse>(
    await api.DELETE("/executions/{execution_id}/tags", { params: { path, query: { tag: edit.tags } } }),
    "Remove execution tags",
  );
}

export const executionTagCommand: CommandDef = {
  name: "tag",
  description: "Add or remove an execution's tags. Idempotent; never replaces the set",
  args: tagEditArgs("execution"),
  examples: [
    "syn execution tag add <execution-id> eval:baseline     # filter later with --tag eval:baseline",
    "syn execution tag remove <execution-id> nightly        # inherited_tags still records it",
  ],
  handler: async (parsed: ParsedArgs) => {
    const data = await send(parseTagEdit(parsed, "execution"));
    print(style(`Tags of ${data.execution_id}`, GREEN));
    printTags("tags:           ", data.tags);
    printTags("inherited_tags: ", data.inherited_tags);
  },
};
