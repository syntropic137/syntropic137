import { describe, expect, it } from "vitest";
import { stripAnsi } from "../../src/output/ansi.js";
import { CommandGroup } from "../../src/framework/command.js";
import type { CommandDef } from "../../src/framework/command.js";
import {
  renderCommandHelp,
  renderGroupHelp,
  renderTopLevelHelp,
} from "../../src/framework/help.js";

const noop = () => {};

describe("renderTopLevelHelp", () => {
  it("includes CLI name and description", () => {
    const output = stripAnsi(
      renderTopLevelHelp("syn", "A test CLI", new Map(), new Map()),
    );
    expect(output).toContain("syn");
    expect(output).toContain("A test CLI");
  });

  it("lists root commands", () => {
    const cmds = new Map<string, CommandDef>([
      ["health", { name: "health", description: "Check health", handler: noop }],
    ]);
    const output = stripAnsi(
      renderTopLevelHelp("syn", "desc", new Map(), cmds),
    );
    expect(output).toContain("health");
    expect(output).toContain("Check health");
  });

  it("lists command groups", () => {
    const group = new CommandGroup("workflow", "Manage workflows");
    const groups = new Map([["workflow", group]]);
    const output = stripAnsi(
      renderTopLevelHelp("syn", "desc", groups, new Map()),
    );
    expect(output).toContain("workflow");
    expect(output).toContain("Manage workflows");
  });
});

describe("renderGroupHelp", () => {
  it("lists commands in the group", () => {
    const group = new CommandGroup("workflow", "Manage workflows");
    group.command({
      name: "list",
      description: "List workflows",
      handler: noop,
    });
    group.command({
      name: "run",
      description: "Run a workflow",
      handler: noop,
    });

    const output = stripAnsi(renderGroupHelp("syn", group));
    expect(output).toContain("list");
    expect(output).toContain("run");
    expect(output).toContain("Manage workflows");
  });
});

describe("renderCommandHelp", () => {
  it("includes usage, args, and options", () => {
    const cmd: CommandDef = {
      name: "install",
      description: "Install a workflow package",
      args: [{ name: "source", description: "Package source", required: true }],
      options: {
        ref: {
          type: "string",
          short: "r",
          description: "Git ref",
          default: "main",
        },
        "dry-run": { type: "boolean", short: "n", description: "Dry run" },
      },
      handler: noop,
    };

    const output = stripAnsi(renderCommandHelp(cmd, "syn", "workflow"));
    expect(output).toContain("syn workflow install");
    expect(output).toContain("<source>");
    expect(output).toContain("--ref");
    expect(output).toContain("-r");
    expect(output).toContain("--dry-run");
    expect(output).toContain("(default: main)");
  });
});
