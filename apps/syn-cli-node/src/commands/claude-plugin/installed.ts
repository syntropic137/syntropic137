// See ADR-066: this lists the local CLI registry only; no API calls.
/**
 * `syn claude-plugin installed` - dump the local CLI registry of installed
 * claude plugins. The API's lock projection is the source of truth for
 * "is it registered with the platform"; this command shows what THIS
 * workstation has installed via `syn claude-plugin install`.
 */

import type { CommandDef, ParsedArgs } from "../../framework/command.js";
import { listInstalled } from "../../packages/claude-plugin-registry.js";
import { print, printDim } from "../../output/console.js";
import { CYAN, DIM } from "../../output/ansi.js";
import { Table } from "../../output/table.js";
import { formatTimestamp } from "../../output/format.js";

export const installedCommand: CommandDef = {
  name: "installed",
  description: "List Claude plugins installed locally via 'syn claude-plugin install'",
  handler: async (_parsed: ParsedArgs) => {
    const entries = listInstalled();
    if (entries.length === 0) {
      printDim("No claude plugins installed locally.");
      return;
    }
    const table = new Table({ title: "Installed Claude Plugins (local cache)" });
    table.addColumn("NAME", { style: CYAN });
    table.addColumn("VERSION");
    table.addColumn("SOURCE", { style: DIM });
    table.addColumn("INSTALLED", { style: DIM });
    table.addColumn("MARKETPLACE", { style: DIM });
    for (const e of entries) {
      table.addRow(
        e.name,
        e.version,
        e.source_url,
        formatTimestamp(e.installed_at),
        e.marketplace_source ?? "-",
      );
    }
    print(table.render());
  },
};
