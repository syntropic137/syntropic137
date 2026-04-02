import { BOLD, CYAN, DIM, style } from "../output/ansi.js";
import type { CommandDef, CommandGroup } from "./command.js";

export function renderTopLevelHelp(
  name: string,
  description: string,
  groups: ReadonlyMap<string, CommandGroup>,
  rootCommands: ReadonlyMap<string, CommandDef>,
): string {
  const lines: string[] = [];

  lines.push(`${style(name, BOLD)} — ${description}`);
  lines.push("");
  lines.push(style("Usage:", BOLD) + `  ${name} <command> [options]`);

  if (rootCommands.size > 0) {
    lines.push("");
    lines.push(style("Commands:", BOLD));
    const maxLen = maxNameLength(rootCommands);
    for (const [cmdName, cmd] of rootCommands) {
      lines.push(
        `  ${style(cmdName.padEnd(maxLen), CYAN)}  ${style(cmd.description, DIM)}`,
      );
    }
  }

  if (groups.size > 0) {
    lines.push("");
    lines.push(style("Command Groups:", BOLD));
    const maxLen = Math.max(...[...groups.values()].map((g) => g.name.length));
    for (const group of groups.values()) {
      lines.push(
        `  ${style(group.name.padEnd(maxLen), CYAN)}  ${style(group.description, DIM)}`,
      );
    }
  }

  lines.push("");
  lines.push(
    style(`Run '${name} <command> --help' for more information on a command.`, DIM),
  );

  return lines.join("\n");
}

export function renderGroupHelp(name: string, group: CommandGroup): string {
  const lines: string[] = [];

  lines.push(`${style(name + " " + group.name, BOLD)} — ${group.description}`);
  lines.push("");
  lines.push(
    style("Usage:", BOLD) + `  ${name} ${group.name} <command> [options]`,
  );
  lines.push("");
  lines.push(style("Commands:", BOLD));

  const maxLen = maxNameLength(group.commands);
  for (const [cmdName, cmd] of group.commands) {
    lines.push(
      `  ${style(cmdName.padEnd(maxLen), CYAN)}  ${style(cmd.description, DIM)}`,
    );
  }

  return lines.join("\n");
}

export function renderCommandHelp(
  command: CommandDef,
  cliName: string,
  groupName?: string,
): string {
  const lines: string[] = [];

  const prefix = groupName
    ? `${cliName} ${groupName} ${command.name}`
    : `${cliName} ${command.name}`;

  lines.push(`${style(prefix, BOLD)} — ${command.description}`);
  lines.push("");

  // Usage line
  let usage = `  ${prefix}`;
  if (command.args) {
    for (const arg of command.args) {
      usage += arg.required !== false ? ` <${arg.name}>` : ` [${arg.name}]`;
    }
  }
  if (command.options && Object.keys(command.options).length > 0) {
    usage += " [options]";
  }
  lines.push(style("Usage:", BOLD) + usage);

  // Arguments
  if (command.args && command.args.length > 0) {
    lines.push("");
    lines.push(style("Arguments:", BOLD));
    const maxLen = Math.max(...command.args.map((a) => a.name.length));
    for (const arg of command.args) {
      const req = arg.required !== false ? " (required)" : "";
      lines.push(
        `  ${style(arg.name.padEnd(maxLen), CYAN)}  ${arg.description}${style(req, DIM)}`,
      );
    }
  }

  // Options
  if (command.options) {
    const entries = Object.entries(command.options);
    if (entries.length > 0) {
      lines.push("");
      lines.push(style("Options:", BOLD));
      const formatted = entries.map(([name, opt]) => {
        const flag = opt.short ? `-${opt.short}, --${name}` : `    --${name}`;
        return { flag, opt };
      });
      const maxLen = Math.max(...formatted.map((f) => f.flag.length));
      for (const { flag, opt } of formatted) {
        const def =
          opt.default !== undefined ? ` ${style(`(default: ${String(opt.default)})`, DIM)}` : "";
        lines.push(`  ${style(flag.padEnd(maxLen), CYAN)}  ${opt.description}${def}`);
      }
    }
  }

  return lines.join("\n");
}

function maxNameLength(
  map: ReadonlyMap<string, { name: string }>,
): number {
  return Math.max(...[...map.values()].map((v) => v.name.length));
}
