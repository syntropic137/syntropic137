/**
 * GitHub App integration commands.
 *
 * Live queries against the GitHub API for App installation data.
 */

import { CommandGroup, type CommandDef, type ParsedArgs } from "../framework/command.js";
import { api, unwrap } from "../client/typed.js";
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
    const installationId = (parsed.values["installation"] as string | undefined) ?? null;
    const includePrivate = parsed.values["include-private"] as boolean | undefined;

    const query: { installation_id?: string | null; include_private?: boolean } = {
      installation_id: installationId,
    };
    if (includePrivate !== undefined) query.include_private = includePrivate;

    const data = unwrap(await api.GET("/github/repos", {
      params: { query },
    }), "List GitHub repos");

    const items = data.repos ?? [];
    if (items.length === 0) { printDim("No accessible repositories found."); return; }

    const table = new Table({ title: "Accessible Repositories" });
    table.addColumn("Repo", { style: CYAN });
    table.addColumn("Owner");
    table.addColumn("Branch", { style: DIM });
    table.addColumn("Private");
    table.addColumn("Installation", { style: DIM });

    for (const r of items) {
      table.addRow(
        r.full_name,
        r.owner,
        r.default_branch,
        r.private ? style("yes", RED) : style("no", GREEN),
        r.installation_id,
      );
    }
    table.print();
  },
};

export const githubGroup = new CommandGroup("github", "GitHub App integration")
  .command(reposCommand);
