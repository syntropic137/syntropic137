// See ADR-066: thin read-only call to the API; no local I/O beyond stdout.
/**
 * `syn skill show <name>` - every registration sharing a name.
 *
 * A name is not unique: the same skill can be pinned at several versions, and
 * two sources can publish the same name. All are shown so the caller can tell
 * which pin a workflow actually resolves to.
 */

import type { CommandDef, ParsedArgs } from "../../framework/command.js";
import { CLIError } from "../../framework/errors.js";
import { api, unwrap } from "../../client/typed.js";
import type { components } from "../../generated/api-types.js";
import { printError, print } from "../../output/console.js";
import { style, BOLD, CYAN, DIM } from "../../output/ansi.js";
import { formatTimestamp } from "../../output/format.js";

type SkillDetail = components["schemas"]["SkillDetailResponse"];

export const showCommand: CommandDef = {
  name: "show",
  description: "Show every registration of a skill name",
  args: [{ name: "name", description: "Skill name", required: true }],
  options: {
    json: { type: "boolean", description: "Emit raw JSON", default: false },
  },
  handler: async (parsed: ParsedArgs) => {
    const name = parsed.positionals[0];
    if (!name) {
      printError("Missing required argument: name");
      throw new CLIError("Missing argument", 1);
    }

    const data = unwrap<SkillDetail>(
      await api.GET("/skills/by-name/{skill_name}", { params: { path: { skill_name: name } } }),
      `Show skill ${name}`,
    );

    if (parsed.values["json"] === true) {
      print(JSON.stringify(data, null, 2));
      return;
    }

    print("");
    print(style(data.skill_name, BOLD));
    for (const r of data.registrations ?? []) {
      print("");
      print(`  ${style(r.version, CYAN)}`);
      print(`    Source:     ${r.source_url}`);
      print(`    Sha:        ${style(r.resolved_sha, DIM)}`);
      print(`    Stored at:  ${style(r.tree_storage_prefix, DIM)}`);
      print(`    Registered: ${style(formatTimestamp(r.registered_at), DIM)}`);
    }
  },
};
