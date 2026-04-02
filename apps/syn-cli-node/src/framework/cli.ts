import { parseArgs } from "node:util";
import { print, printError } from "../output/console.js";
import type { CommandDef, CommandGroup, ParsedArgs } from "./command.js";
import { CLIError } from "./errors.js";
import { renderCommandHelp, renderGroupHelp, renderTopLevelHelp } from "./help.js";

export class CLI {
  private readonly name: string;
  private readonly description: string;
  private readonly version: string;
  private readonly groups = new Map<string, CommandGroup>();
  private readonly rootCommands = new Map<string, CommandDef>();

  constructor(options: { name: string; description: string; version: string }) {
    this.name = options.name;
    this.description = options.description;
    this.version = options.version;
  }

  addGroup(group: CommandGroup): this {
    this.groups.set(group.name, group);
    return this;
  }

  addCommand(def: CommandDef): this {
    this.rootCommands.set(def.name, def);
    return this;
  }

  async run(argv?: readonly string[]): Promise<void> {
    const args = argv ?? process.argv.slice(2);

    try {
      await this.dispatch(args);
    } catch (err) {
      if (err instanceof CLIError) {
        printError(err.message);
        process.exit(err.exitCode);
      }
      printError(`Unexpected error: ${String(err)}`);
      process.exit(2);
    }
  }

  private async dispatch(args: readonly string[]): Promise<void> {
    const first = args[0];

    if (!first || first === "--help" || first === "-h") {
      print(renderTopLevelHelp(this.name, this.description, this.groups, this.rootCommands));
      process.exit(0);
    }

    if (first === "--version") {
      print(`${this.name} v${this.version}`);
      process.exit(0);
    }

    const rootCmd = this.rootCommands.get(first);
    if (rootCmd) {
      await this.executeCommand(rootCmd, args.slice(1));
      return;
    }

    const group = this.groups.get(first);
    if (group) {
      await this.dispatchGroup(first, group, args.slice(1));
      return;
    }

    throw new CLIError(`Unknown command: ${first}. Run '${this.name} --help' for usage.`);
  }

  private async dispatchGroup(
    groupName: string,
    group: CommandGroup,
    args: readonly string[],
  ): Promise<void> {
    const second = args[0];

    if (!second || second === "--help" || second === "-h") {
      print(renderGroupHelp(this.name, group));
      process.exit(0);
    }

    const cmd = group.getCommand(second);
    if (!cmd) {
      throw new CLIError(
        `Unknown command: ${groupName} ${second}. Run '${this.name} ${groupName} --help' for usage.`,
      );
    }

    await this.executeCommand(cmd, args.slice(1), group.name);
  }

  private async executeCommand(
    cmd: CommandDef,
    argv: readonly string[],
    groupName?: string,
  ): Promise<void> {
    const parsed = this.parseCommandArgs(cmd, argv);
    if (parsed.values["help"]) {
      print(renderCommandHelp(cmd, this.name, groupName));
      process.exit(0);
    }
    await cmd.handler(parsed);
  }

  private parseCommandArgs(
    cmd: CommandDef,
    argv: readonly string[],
  ): ParsedArgs {
    const optionsConfig = buildOptionsConfig(cmd);

    try {
      const { values, positionals } = parseArgs({
        args: argv as string[],
        options: optionsConfig,
        allowPositionals: true,
        strict: true,
      });

      return {
        positionals,
        values: values as ParsedArgs["values"],
      };
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      throw new CLIError(msg);
    }
  }
}

function buildOptionsConfig(
  cmd: CommandDef,
): Record<string, { type: "string" | "boolean"; short?: string; multiple?: boolean; default?: string | boolean }> {
  const config: Record<
    string,
    { type: "string" | "boolean"; short?: string; multiple?: boolean; default?: string | boolean }
  > = {
    help: { type: "boolean", short: "h", default: false },
  };

  if (!cmd.options) return config;

  for (const [name, def] of Object.entries(cmd.options)) {
    const entry: { type: "string" | "boolean"; short?: string; multiple?: boolean; default?: string | boolean } = {
      type: def.type,
    };
    if (def.short) entry.short = def.short;
    if (def.multiple) entry.multiple = def.multiple;
    if (def.default !== undefined) entry.default = def.default;
    config[name] = entry;
  }

  return config;
}
