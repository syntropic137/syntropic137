/**
 * Shared shape of `syn execution tag` and `syn workflow tag` (#967).
 *
 * Both take `add|remove <id> <tag...>`. Edits are idempotent and never
 * replace the set: adding a tag already present, or removing one that is
 * absent, succeeds and changes nothing. The server normalises and validates
 * every tag, so the CLI passes them through as typed and prints the set the
 * server answers with.
 */

import type { ArgDef, ParsedArgs } from "../framework/command.js";
import { CLIError } from "../framework/errors.js";
import { print, printDim, printError } from "../output/console.js";

export type TagAction = "add" | "remove";

export interface TagEdit {
  action: TagAction;
  id: string;
  tags: string[];
}

export function tagEditArgs(entity: string): readonly ArgDef[] {
  return [
    { name: "action", description: "add or remove", required: true },
    { name: `${entity}-id`, description: `The ${entity} to edit`, required: true },
    { name: "tags", description: "One or more tags", required: true },
  ];
}

/** Parse `add|remove <id> <tag...>`, or fail naming what is missing. */
export function parseTagEdit(parsed: ParsedArgs, entity: string): TagEdit {
  const [action, id, ...tags] = parsed.positionals;
  if (action !== "add" && action !== "remove") {
    printError(`Expected 'add' or 'remove', got ${action === undefined ? "nothing" : `'${action}'`}`);
    printDim(`Usage: syn ${entity} tag add|remove <${entity}-id> <tag...>`);
    throw new CLIError("Invalid arguments", 1);
  }
  if (!id || tags.length === 0) {
    printError(`${entity}-id and at least one tag are required`);
    printDim(`Usage: syn ${entity} tag ${action} <${entity}-id> <tag...>`);
    throw new CLIError("Missing argument", 1);
  }
  return { action, id, tags };
}

export function printTags(label: string, tags: readonly string[]): void {
  print(`  ${label}${tags.length > 0 ? tags.join(", ") : "(none)"}`);
}
