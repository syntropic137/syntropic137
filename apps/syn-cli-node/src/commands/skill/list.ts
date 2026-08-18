// See ADR-066: thin read-only call to the API; no local I/O beyond stdout.
/**
 * `syn skill list` - what is registered.
 */

import type { CommandDef, ParsedArgs } from "../../framework/command.js";
import { api, unwrap } from "../../client/typed.js";
import type { components } from "../../generated/api-types.js";
import { printDim, print } from "../../output/console.js";
import { CYAN, DIM } from "../../output/ansi.js";
import { Table } from "../../output/table.js";
import { formatTimestamp } from "../../output/format.js";

type SkillSummary = components["schemas"]["SkillRegistrationSummary"];
type SkillList = components["schemas"]["SkillListResponse"];

export const listCommand: CommandDef = {
  name: "list",
  description: "List every registered skill",
  options: {
    json: { type: "boolean", description: "Emit raw JSON", default: false },
  },
  handler: async (parsed: ParsedArgs) => {
    const data = unwrap<SkillList>(await api.GET("/skills", {}), "List skills");

    if (parsed.values["json"] === true) {
      print(JSON.stringify(data, null, 2));
      return;
    }

    const items = data.skills ?? [];
    if (items.length === 0) {
      printDim("No skills registered.");
      printDim("Skills register automatically when you run `syn workflow install`.");
      return;
    }
    renderTable(items);
  },
};

function renderTable(items: readonly SkillSummary[]): void {
  const table = new Table({ title: "Skills" });
  table.addColumn("NAME", { style: CYAN });
  table.addColumn("VERSION");
  table.addColumn("SOURCE");
  table.addColumn("SHA", { style: DIM });
  table.addColumn("REGISTERED", { style: DIM });
  for (const e of items) {
    table.addRow(
      e.skill_name,
      e.version,
      e.source_url,
      e.resolved_sha_display,
      formatTimestamp(e.registered_at),
    );
  }
  table.print();
}
