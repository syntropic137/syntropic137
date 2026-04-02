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
      print(
        renderTopLevelHelp(
          this.name,
          this.description,
          this.groups,
          this.rootCommands,
        ),
      );
      process.exit(0);
    }

    if (first === "--version") {
      print(`${this.name} v${this.version}`);
      process.exit(0);
    }

    // Root command?
    const rootCmd = this.rootCommands.get(first);
    if (rootCmd) {
      const parsed = this.parseCommandArgs(rootCmd, args.slice(1));
      if (parsed.values["help"]) {
        print(renderCommandHelp(rootCmd, this.name));
        process.exit(0);
      }
      await rootCmd.handler(parsed);
      return;
    }

    // Command group?
    const group = this.groups.get(first);
    if (group) {
      const second = args[1];

      if (!second || second === "--help" || second === "-h") {
        print(renderGroupHelp(this.name, group));
        process.exit(0);
      }

      const cmd = group.getCommand(second);
      if (!cmd) {
        printError(`Unknown command: ${first} ${second}`);
        print("");
        print(renderGroupHelp(this.name, group));
        throw new CLIError(`Unknown command: ${first} ${second}`);
      }

      const parsed = this.parseCommandArgs(cmd, args.slice(2));
      if (parsed.values["help"]) {
        print(renderCommandHelp(cmd, this.name, group.name));
        process.exit(0);
      }
      await cmd.handler(parsed);
      return;
    }

    printError(`Unknown command: ${first}`);
    print("");
    print(
      renderTopLevelHelp(
        this.name,
        this.description,
        this.groups,
        this.rootCommands,
      ),
    );
    throw new CLIError(`Unknown command: ${first}`);
  }

  private parseCommandArgs(
    cmd: CommandDef,
    argv: readonly string[],
  ): ParsedArgs {
    const optionsConfig: Record<
      string,
      { type: "string" | "boolean"; short?: string; multiple?: boolean; default?: string | boolean }
    > = {
      help: { type: "boolean", short: "h", default: false },
    };

    if (cmd.options) {
      for (const [name, def] of Object.entries(cmd.options)) {
        const entry: { type: "string" | "boolean"; short?: string; multiple?: boolean; default?: string | boolean } = {
          type: def.type,
        };
        if (def.short) entry.short = def.short;
        if (def.multiple) entry.multiple = def.multiple;
        if (def.default !== undefined) entry.default = def.default;
        optionsConfig[name] = entry;
      }
    }

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
  }
}
