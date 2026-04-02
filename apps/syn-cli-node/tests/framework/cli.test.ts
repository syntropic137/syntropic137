import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CLI } from "../../src/framework/cli.js";
import { CommandGroup } from "../../src/framework/command.js";
import { CLIError } from "../../src/framework/errors.js";

describe("CLI", () => {
  let exitSpy: ReturnType<typeof vi.spyOn>;
  let stdoutSpy: ReturnType<typeof vi.spyOn>;
  let stderrSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    exitSpy = vi
      .spyOn(process, "exit")
      .mockImplementation((() => {}) as unknown as (code?: number) => never);
    stdoutSpy = vi.spyOn(process.stdout, "write").mockReturnValue(true);
    stderrSpy = vi.spyOn(process.stderr, "write").mockReturnValue(true);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  function createCli(): CLI {
    return new CLI({
      name: "syn",
      description: "Test CLI",
      version: "1.0.0",
    });
  }

  it("prints help on --help", async () => {
    const cli = createCli();
    await cli.run(["--help"]);
    expect(exitSpy).toHaveBeenCalledWith(0);
    const output = stdoutSpy.mock.calls.map((c) => String(c[0])).join("");
    expect(output).toContain("syn");
    expect(output).toContain("Test CLI");
  });

  it("prints version on --version", async () => {
    const cli = createCli();
    await cli.run(["--version"]);
    expect(exitSpy).toHaveBeenCalledWith(0);
    const output = stdoutSpy.mock.calls.map((c) => String(c[0])).join("");
    expect(output).toContain("1.0.0");
  });

  it("routes to root command", async () => {
    const handler = vi.fn();
    const cli = createCli();
    cli.addCommand({ name: "health", description: "Check health", handler });
    await cli.run(["health"]);
    expect(handler).toHaveBeenCalledOnce();
  });

  it("routes to command group", async () => {
    const handler = vi.fn();
    const cli = createCli();
    const group = new CommandGroup("workflow", "Manage workflows");
    group.command({ name: "list", description: "List", handler });
    cli.addGroup(group);
    await cli.run(["workflow", "list"]);
    expect(handler).toHaveBeenCalledOnce();
  });

  it("shows group help when no subcommand", async () => {
    const cli = createCli();
    const group = new CommandGroup("workflow", "Manage workflows");
    group.command({
      name: "list",
      description: "List",
      handler: vi.fn(),
    });
    cli.addGroup(group);
    await cli.run(["workflow"]);
    expect(exitSpy).toHaveBeenCalledWith(0);
    const output = stdoutSpy.mock.calls.map((c) => String(c[0])).join("");
    expect(output).toContain("list");
  });

  it("exits with 1 on unknown command", async () => {
    const cli = createCli();
    await cli.run(["nonexistent"]);
    expect(exitSpy).toHaveBeenCalledWith(1);
    const errOutput = stderrSpy.mock.calls.map((c) => String(c[0])).join("");
    expect(errOutput).toContain("Unknown command");
  });

  it("handles CLIError from handler", async () => {
    const cli = createCli();
    cli.addCommand({
      name: "fail",
      description: "Fails",
      handler: () => {
        throw new CLIError("Something broke", 3);
      },
    });
    await cli.run(["fail"]);
    expect(exitSpy).toHaveBeenCalledWith(3);
    const errOutput = stderrSpy.mock.calls.map((c) => String(c[0])).join("");
    expect(errOutput).toContain("Something broke");
  });

  it("parses command options", async () => {
    const handler = vi.fn();
    const cli = createCli();
    cli.addCommand({
      name: "test",
      description: "Test command",
      options: {
        name: { type: "string", short: "n", description: "Name" },
        verbose: {
          type: "boolean",
          short: "v",
          description: "Verbose",
          default: false,
        },
      },
      handler,
    });
    await cli.run(["test", "--name", "foo", "-v"]);
    expect(handler).toHaveBeenCalledOnce();
    const parsed = handler.mock.calls[0]![0]!;
    expect(parsed.values["name"]).toBe("foo");
    expect(parsed.values["verbose"]).toBe(true);
  });

  it("passes positionals to handler", async () => {
    const handler = vi.fn();
    const cli = createCli();
    cli.addCommand({
      name: "greet",
      description: "Greet",
      args: [{ name: "name", description: "Name" }],
      handler,
    });
    await cli.run(["greet", "world"]);
    expect(handler.mock.calls[0]![0]!.positionals).toEqual(["world"]);
  });
});
