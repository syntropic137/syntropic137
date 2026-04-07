/**
 * Organization management commands — CRUD.
 * Port of apps/syn-cli/src/syn_cli/commands/org.py
 */

import { CommandGroup, type CommandDef, type ParsedArgs } from "../framework/command.js";
import { CLIError } from "../framework/errors.js";
import { api, unwrap } from "../client/typed.js";
import { print, printError, printDim, printSuccess } from "../output/console.js";
import { style, BOLD, CYAN, DIM } from "../output/ansi.js";
import { Table } from "../output/table.js";


function reqId(parsed: ParsedArgs): string {
  const id = parsed.positionals[0];
  if (!id) { printError("Missing org-id"); throw new CLIError("Missing argument", 1); }
  return id;
}

const createCommand: CommandDef = {
  name: "create",
  description: "Create a new organization",
  options: {
    name: { type: "string", short: "n", description: "Organization name" },
    slug: { type: "string", short: "s", description: "URL-safe slug" },
  },
  handler: async (parsed: ParsedArgs) => {
    const name = parsed.values["name"] as string | undefined;
    const slug = parsed.values["slug"] as string | undefined;
    if (!name) { printError("Missing --name"); throw new CLIError("Missing option", 1); }

    const body = { name, slug: slug ?? "", created_by: "cli" as const };

    const d = unwrap(await api.POST("/organizations", { body }), "Create organization");
    printSuccess(`Organization created: ${d.organization_id}`);
    print(`  Name: ${d.name ?? name}`);
    if (d.slug) print(`  Slug: ${d.slug}`);
  },
};

const listCommand: CommandDef = {
  name: "list",
  description: "List all organizations",
  handler: async () => {
    const d = unwrap(await api.GET("/organizations"), "List organizations");
    const items = d.organizations ?? [];
    if (items.length === 0) { printDim("No organizations found."); return; }

    const table = new Table({ title: "Organizations" });
    table.addColumn("ID", { style: CYAN });
    table.addColumn("Name");
    table.addColumn("Slug", { style: DIM });
    table.addColumn("Systems", { align: "right" });
    table.addColumn("Repos", { align: "right" });

    for (const o of items) {
      table.addRow(
        o.organization_id,
        o.name,
        o.slug,
        String(o.system_count),
        String(o.repo_count),
      );
    }
    table.print();
  },
};

const showCommand: CommandDef = {
  name: "show",
  description: "Show organization details",
  args: [{ name: "org-id", description: "Organization ID", required: true }],
  handler: async (parsed: ParsedArgs) => {
    const id = reqId(parsed);
    const d = unwrap(await api.GET("/organizations/{organization_id}", { params: { path: { organization_id: id } } }), "Get organization");
    print(`${style("Organization:", BOLD)} ${d.name}`);
    print(`  ID:      ${d.organization_id}`);
    if (d.slug) print(`  Slug:    ${d.slug}`);
    print(`  Systems: ${d.system_count}`);
    print(`  Repos:   ${d.repo_count}`);
  },
};

const updateCommand: CommandDef = {
  name: "update",
  description: "Update an organization",
  args: [{ name: "org-id", description: "Organization ID", required: true }],
  options: {
    name: { type: "string", short: "n", description: "New name" },
    slug: { type: "string", short: "s", description: "New slug" },
  },
  handler: async (parsed: ParsedArgs) => {
    const id = reqId(parsed);
    const name = parsed.values["name"] as string | undefined;
    const slug = parsed.values["slug"] as string | undefined;
    if (!name && !slug) { printError("Nothing to update. Use --name or --slug."); throw new CLIError("No updates", 1); }

    const body = {
      ...(name ? { name } : {}),
      ...(slug ? { slug } : {}),
    };
    unwrap(await api.PUT("/organizations/{organization_id}", { params: { path: { organization_id: id } }, body }), "Update organization");
    printSuccess(`Organization ${id} updated.`);
  },
};

const deleteCommand: CommandDef = {
  name: "delete",
  description: "Delete an organization",
  args: [{ name: "org-id", description: "Organization ID", required: true }],
  options: {
    force: { type: "boolean", short: "f", description: "Skip confirmation", default: false },
  },
  handler: async (parsed: ParsedArgs) => {
    const id = reqId(parsed);
    if (parsed.values["force"] !== true) {
      printError(`Use --force to confirm deleting organization ${id}`);
      throw new CLIError("Confirmation required", 1);
    }
    unwrap(await api.DELETE("/organizations/{organization_id}", { params: { path: { organization_id: id } } }), "Delete organization");
    printSuccess(`Organization ${id} deleted.`);
  },
};

export const orgGroup = new CommandGroup("org", "Manage organizations");
orgGroup.command(createCommand).command(listCommand).command(showCommand).command(updateCommand).command(deleteCommand);
