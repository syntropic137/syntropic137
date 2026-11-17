/** `syn execution pushes <execution-id>`: the pushes its phases recorded (#1544). */

import type { CommandDef } from "../framework/command.js";
import { CLIError } from "../framework/errors.js";
import { api, unwrap } from "../client/typed.js";
import type { components } from "../generated/api-types.js";
import { print } from "../output/console.js";

type ExecutionPushesResponse = components["schemas"]["ExecutionPushesResponse"];

export const executionPushesCommand: CommandDef = {
  name: "pushes",
  description: "List the pushes an execution's phases recorded (PhaseCommitPushed): phase, repository, branch, SHA",
  args: [{ name: "execution-id", description: "Execution ID or unique prefix", required: true }],
  options: {
    json: { type: "boolean", description: "Print the response as JSON" },
  },
  examples: [
    "syn execution pushes <execution-id>          # one line per push, in recorded order",
    "syn execution pushes <execution-id> --json   # for scripts and agents",
  ],
  handler: async ({ positionals, values }) => {
    const [execution] = positionals;
    if (!execution) throw new CLIError("execution-id is required");
    const data = unwrap<ExecutionPushesResponse>(
      await api.GET("/executions/{execution_id}/pushes", { params: { path: { execution_id: execution } } }),
      "Failed to read recorded pushes",
    );
    if (values["json"] === true) {
      print(JSON.stringify(data));
      return;
    }
    if (data.pushes.length === 0) {
      print(`${data.execution_id}: no PhaseCommitPushed recorded`);
      return;
    }
    for (const p of data.pushes) print(`${p.phase_id}\t${p.repository}\t${p.branch}\t${p.sha}`);
  },
};
