export interface ArgDef {
  name: string;
  description: string;
  required?: boolean;
}

export interface OptionDef {
  type: "string" | "boolean";
  short?: string;
  description: string;
  multiple?: boolean;
  default?: string | boolean;
}

export interface ParsedArgs {
  positionals: readonly string[];
  values: Record<string, string | boolean | readonly string[] | undefined>;
}

export interface CommandDef {
  name: string;
  description: string;
  args?: readonly ArgDef[];
  options?: Record<string, OptionDef>;
  handler: (parsed: ParsedArgs) => void | Promise<void>;
}

export class CommandGroup {
  readonly name: string;
  readonly description: string;
  /**
   * Prose for the generated docs page, for context that does not fit the
   * one-line `description` shown in the padded `--help` column.
   */
  readonly notes: string | undefined;
  private readonly _commands = new Map<string, CommandDef>();

  constructor(name: string, description: string, notes?: string) {
    this.name = name;
    this.description = description;
    this.notes = notes;
  }

  get commands(): ReadonlyMap<string, CommandDef> {
    return this._commands;
  }

  command(def: CommandDef): this {
    this._commands.set(def.name, def);
    return this;
  }

  getCommand(name: string): CommandDef | undefined {
    return this._commands.get(name);
  }
}
