import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CLI } from "../../src/framework/cli.js";
import { CommandGroup } from "../../src/framework/command.js";
import { CLIError } from "../../src/framework/errors.js";
import { printError } from "../../src/output/console.js";

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
    vi.resetAllMocks();
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

  describe("preflight (#1473)", () => {
    function cliWith(preflight: () => Promise<void>): CLI {
      const cli = new CLI({ name: "syn", description: "Test CLI", version: "1.0.0", preflight });
      cli.addCommand({ name: "test", description: "Test", handler: vi.fn() });
      cli.addCommand({ name: "local", description: "Local", skipPreflight: true, handler: vi.fn() });
      const group = new CommandGroup("workflow", "Manage workflows");
      group.command({ name: "list", description: "List", handler: vi.fn() });
      cli.addGroup(group);
      return cli;
    }

    // The trap the hook exists for: handlers print their own error BEFORE
    // throwing (workflow/resolver.ts), so a warning printed from run()'s catch
    // or after the handler would arrive after the error it explains.
    it("speaks before the handler's own error output", async () => {
      const events: string[] = [];
      stdoutSpy.mockImplementation((chunk: unknown) => (events.push(String(chunk)), true));
      stderrSpy.mockImplementation((chunk: unknown) => (events.push(String(chunk)), true));

      const cli = new CLI({
        name: "syn",
        description: "Test CLI",
        version: "1.0.0",
        preflight: async () => {
          process.stderr.write("Warning: releases differ\n");
        },
      });
      cli.addCommand({
        name: "resolve",
        description: "Resolve",
        handler: () => {
          printError("No workflow found matching: x");
          throw new CLIError("Workflow not found", 1);
        },
      });
      await cli.run(["resolve"]);

      const at = (needle: string) => events.findIndex((e) => e.includes(needle));
      expect(at("Warning: releases differ")).toBeGreaterThanOrEqual(0);
      expect(at("Warning: releases differ")).toBeLessThan(at("No workflow found"));
      expect(at("No workflow found")).toBeLessThan(at("Workflow not found"));
      expect(exitSpy).toHaveBeenCalledWith(1);
    });

    it("runs exactly once per command", async () => {
      const preflight = vi.fn(async () => {});
      await cliWith(preflight).run(["workflow", "list"]);
      expect(preflight).toHaveBeenCalledOnce();
    });

    it("is skipped for a command that sets skipPreflight", async () => {
      const preflight = vi.fn(async () => {});
      await cliWith(preflight).run(["local"]);
      expect(preflight).not.toHaveBeenCalled();
    });

    it.each([["--help"], ["--version"], ["workflow"], ["test --help"], ["workflow list --help"]])(
      "is never reached by `%s`",
      async (argv) => {
        const preflight = vi.fn(async () => {});
        await cliWith(preflight).run(argv.split(" "));
        expect(preflight).not.toHaveBeenCalled();
      },
    );

    it("is not reached when the arguments do not parse", async () => {
      const preflight = vi.fn(async () => {});
      await cliWith(preflight).run(["test", "--nope"]);
      expect(preflight).not.toHaveBeenCalled();
      expect(exitSpy).toHaveBeenCalledWith(1);
    });
  });
});
