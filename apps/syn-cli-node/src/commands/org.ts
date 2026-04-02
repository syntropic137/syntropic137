/**
 * Organization management commands — CRUD.
 * Port of apps/syn-cli/src/syn_cli/commands/org.py
 */

import { CommandGroup, type CommandDef, type ParsedArgs } from "../framework/command.js";
import { CLIError } from "../framework/errors.js";
import { apiGet, apiGetList, apiPost, apiPut, apiDelete } from "../client/api.js";
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

    const body: Record<string, unknown> = { name };
    if (slug) body["slug"] = slug;

    const d = await apiPost<Record<string, unknown>>("/organizations", { body, expected: [200, 201] });
    printSuccess(`Organization created: ${d["organization_id"] ?? ""}`);
    print(`  Name: ${d["name"] ?? name}`);
    if (d["slug"]) print(`  Slug: ${String(d["slug"])}`);
  },
};

const listCommand: CommandDef = {
  name: "list",
  description: "List all organizations",
  handler: async () => {
    const items = await apiGetList<Record<string, unknown>>("/organizations");
    if (items.length === 0) { printDim("No organizations found."); return; }

    const table = new Table({ title: "Organizations" });
    table.addColumn("ID", { style: CYAN });
    table.addColumn("Name");
    table.addColumn("Slug", { style: DIM });
    table.addColumn("Systems", { align: "right" });
    table.addColumn("Repos", { align: "right" });

    for (const o of items) {
      table.addRow(
        String(o["organization_id"] ?? ""),
        String(o["name"] ?? ""),
        String(o["slug"] ?? ""),
        String(o["system_count"] ?? 0),
        String(o["repo_count"] ?? 0),
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
    const d = await apiGet<Record<string, unknown>>(`/organizations/${id}`);
    print(`${style("Organization:", BOLD)} ${d["name"] ?? id}`);
    print(`  ID:      ${d["organization_id"] ?? id}`);
    if (d["slug"]) print(`  Slug:    ${String(d["slug"])}`);
    print(`  Systems: ${d["system_count"] ?? 0}`);
    print(`  Repos:   ${d["repo_count"] ?? 0}`);
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
    const body: Record<string, unknown> = {};
    const name = parsed.values["name"] as string | undefined;
    const slug = parsed.values["slug"] as string | undefined;
    if (name) body["name"] = name;
    if (slug) body["slug"] = slug;
    if (Object.keys(body).length === 0) { printError("Nothing to update. Use --name or --slug."); throw new CLIError("No updates", 1); }

    await apiPut(`/organizations/${id}`, { body });
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
    await apiDelete(`/organizations/${id}`);
    printSuccess(`Organization ${id} deleted.`);
  },
};

export const orgGroup = new CommandGroup("org", "Manage organizations");
orgGroup.command(createCommand).command(listCommand).command(showCommand).command(updateCommand).command(deleteCommand);
