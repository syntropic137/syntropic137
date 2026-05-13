// See ADR-066: thin read-only call to the API; no local I/O beyond stdout.
/**
 * `syn claude-plugin list` - dump the lock projection.
 */

import type { CommandDef, ParsedArgs } from "../../framework/command.js";
import { api, unwrap } from "../../client/typed.js";
import type { components } from "../../generated/api-types.js";
import { printDim, print } from "../../output/console.js";
import { CYAN } from "../../output/ansi.js";
import { Table } from "../../output/table.js";
import { formatTimestamp } from "../../output/format.js";

type LockEntry = components["schemas"]["ClaudePluginLockResponse"];
type LockList = components["schemas"]["ClaudePluginLockListResponse"];

export const listCommand: CommandDef = {
  name: "list",
  description: "List all registered Claude plugins",
  handler: async (_parsed: ParsedArgs) => {
    const data = unwrap<LockList>(
      await api.GET("/claude-plugins", {}),
      "List claude plugins",
    );
    const items = data.plugins ?? [];
    if (items.length === 0) {
      printDim("No claude plugins registered.");
      return;
    }
    renderLockTable(items);
  },
};

function renderLockTable(items: readonly LockEntry[]): void {
  const table = new Table({ title: "Claude Plugins" });
  table.addColumn("NAME", { style: CYAN });
  table.addColumn("VERSION");
  table.addColumn("SOURCE");
  table.addColumn("REGISTERED");
  for (const e of items) {
    table.addRow(e.name, e.version, e.source_url, formatTimestamp(e.registered_at));
  }
  print(table.render());
}
