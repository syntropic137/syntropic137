/**
 * Agent interaction commands — list providers, test.
 * Port of apps/syn-cli/src/syn_cli/commands/agent.py
 * Note: chat command omitted (requires interactive stdin, not suited for non-interactive CLI).
 */

import { CommandGroup, type CommandDef, type ParsedArgs } from "../framework/command.js";
import { apiGetList, apiPost } from "../client/api.js";
import { print } from "../output/console.js";
import { style, CYAN, GREEN } from "../output/ansi.js";
import { Table } from "../output/table.js";

const listCommand: CommandDef = {
  name: "list",
  description: "List available agent providers",
  handler: async () => {
    const providers = await apiGetList<Record<string, unknown>>("/agents/providers");

    const table = new Table({ title: "Agent Providers" });
    table.addColumn("Provider", { style: CYAN });
    table.addColumn("Display Name");
    table.addColumn("Available");
    table.addColumn("Default Model");

    for (const p of providers) {
      const available = p["available"]
        ? style("Yes", GREEN)
        : style("No", "\x1b[31m");
      table.addRow(
        String(p["provider"] ?? ""),
        String(p["display_name"] ?? ""),
        available,
        String(p["default_model"] ?? ""),
      );
    }
    table.print();
  },
};

const testCommand: CommandDef = {
  name: "test",
  description: "Test an agent provider with a simple prompt",
  options: {
    provider: { type: "string", short: "p", description: "Agent provider (claude, mock)", default: "claude" },
    prompt: { type: "string", description: "Test prompt", default: "Say hello in one sentence." },
    model: { type: "string", short: "m", description: "Model override" },
  },
  handler: async (parsed: ParsedArgs) => {
    const provider = (parsed.values["provider"] as string | undefined) ?? "claude";
    const prompt = (parsed.values["prompt"] as string | undefined) ?? "Say hello in one sentence.";
    const model = (parsed.values["model"] as string | undefined) ?? null;

    const result = await apiPost<Record<string, unknown>>("/agents/test", {
      body: { provider, prompt, model },
      timeoutMs: 60_000,
    });

    print(`${style(`Response from ${String(result["provider"] ?? provider)}:`, GREEN)}`);
    print(`  Model: ${String(result["model"] ?? "unknown")}`);
    print(`  Response: ${String(result["response_text"] ?? "")}`);
    print(`  Tokens: ${String(result["input_tokens"] ?? 0)} in / ${String(result["output_tokens"] ?? 0)} out`);
  },
};

export const agentGroup = new CommandGroup("agent", "AI agent management and testing");
agentGroup.command(listCommand).command(testCommand);
