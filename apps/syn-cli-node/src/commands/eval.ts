/**
 * `syn eval attach|detach <execution-id> <eval-id>` (#967).
 *
 * Membership lives on the execution: a run belongs to at most one eval. Attach
 * works in any status and never copies the eval's baseline; attaching to the
 * eval the run already belongs to changes nothing, and moving it to another
 * eval needs a detach first. Detach names the eval so it cannot take a run out
 * of an eval it has since moved to, and it keeps the launch record.
 */

import { CommandGroup, type CommandDef, type ParsedArgs } from "../framework/command.js";
import { CLIError } from "../framework/errors.js";
import { api, unwrap } from "../client/typed.js";
import type { components } from "../generated/api-types.js";
import { print, printDim, printError } from "../output/console.js";
import { style, GREEN } from "../output/ansi.js";

type ExecutionEvalResponse = components["schemas"]["ExecutionEvalResponse"];

const membershipArgs = [
  { name: "execution-id", description: "The execution (partial match supported)", required: true },
  { name: "eval-id", description: "The eval", required: true },
] as const;

function parseMembership(parsed: ParsedArgs, verb: string): { executionId: string; evalId: string } {
  const [executionId, evalId] = parsed.positionals;
  if (!executionId || !evalId) {
    printError("execution-id and eval-id are required");
    printDim(`Usage: syn eval ${verb} <execution-id> <eval-id>`);
    throw new CLIError("Missing argument", 1);
  }
  return { executionId, evalId };
}

function printMembership(data: ExecutionEvalResponse): void {
  print(style(`Eval membership of ${data.execution_id}`, GREEN));
  print(`  eval_id:          ${data.eval_id ?? "(none)"}`);
  print(`  association_kind: ${data.association_kind ?? "(none)"}`);
  print(`  launched_eval_id: ${data.launched_eval_id ?? "(none)"}`);
}

const attachCommand: CommandDef = {
  name: "attach",
  description: "Attach an execution to an eval, in any status. Idempotent; never copies the baseline",
  args: membershipArgs,
  examples: ["syn eval attach <execution-id> eval-planning   # association_kind: attached"],
  handler: async (parsed: ParsedArgs) => {
    const { executionId, evalId } = parseMembership(parsed, "attach");
    const data = unwrap<ExecutionEvalResponse>(
      await api.POST("/executions/{execution_id}/eval", {
        params: { path: { execution_id: executionId } },
        body: { eval_id: evalId },
      }),
      "Attach execution to eval",
    );
    printMembership(data);
  },
};

const detachCommand: CommandDef = {
  name: "detach",
  description: "Detach an execution from its eval. launched_eval_id still records the launch",
  args: membershipArgs,
  examples: ["syn eval detach <execution-id> eval-planning"],
  handler: async (parsed: ParsedArgs) => {
    const { executionId, evalId } = parseMembership(parsed, "detach");
    const data = unwrap<ExecutionEvalResponse>(
      await api.DELETE("/executions/{execution_id}/eval", {
        params: { path: { execution_id: executionId }, query: { eval_id: evalId } },
      }),
      "Detach execution from eval",
    );
    printMembership(data);
  },
};

export const evalGroup = new CommandGroup("eval", "Put executions in evals and take them out");
evalGroup.command(attachCommand).command(detachCommand);
