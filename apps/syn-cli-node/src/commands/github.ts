/**
 * GitHub App integration commands.
 *
 * Live queries against the GitHub API for App installation data.
 */

import { CommandGroup, type CommandDef, type ParsedArgs } from "../framework/command.js";
import { apiGetPaginated, buildParams } from "../client/api.js";
import { printDim } from "../output/console.js";
import { style, CYAN, DIM, GREEN, RED } from "../output/ansi.js";
import { Table } from "../output/table.js";

const reposCommand: CommandDef = {
  name: "repos",
  description: "List repositories accessible to the GitHub App",
  options: {
    installation: { type: "string", short: "i", description: "Filter by installation ID" },
    "include-private": { type: "boolean", description: "Include private repos (default: true)" },
  },
  handler: async (parsed: ParsedArgs) => {
    const params = buildParams({
      installation_id: (parsed.values["installation"] as string | undefined) ?? null,
      include_private: (parsed.values["include-private"] as boolean | undefined) ?? null,
    });
    const items = await apiGetPaginated<Record<string, unknown>>("/github/repos", "repos", { params });
    if (items.length === 0) { printDim("No accessible repositories found."); return; }

    const table = new Table({ title: "Accessible Repositories" });
    table.addColumn("Repo", { style: CYAN });
    table.addColumn("Owner");
    table.addColumn("Branch", { style: DIM });
    table.addColumn("Private");
    table.addColumn("Installation", { style: DIM });

    for (const r of items) {
      const isPrivate = r["private"] === true;
      table.addRow(
        String(r["full_name"] ?? ""),
        String(r["owner"] ?? ""),
        String(r["default_branch"] ?? ""),
        isPrivate ? style("yes", RED) : style("no", GREEN),
        String(r["installation_id"] ?? ""),
      );
    }
    table.print();
  },
};

export const githubGroup = new CommandGroup("github", "GitHub App integration")
  .command(reposCommand);
