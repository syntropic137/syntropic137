import type { SyntropicClient } from "../client.js";
import { formatError } from "../errors.js";
import type { ExecutionDetail, PhaseExecutionInfo } from "../types.js";
import { buildMarkdownTable } from "./format.js";

// ---------------------------------------------------------------------------
// syn_get_execution
// ---------------------------------------------------------------------------

export interface GetExecutionArgs {
  execution_id: string;
}

export async function synGetExecution(
  client: SyntropicClient,
  args: GetExecutionArgs,
): Promise<{ content: string; isError?: true }> {
  const result = await client.get<ExecutionDetail>(
    `/executions/${encodeURIComponent(args.execution_id)}`,
  );
  if (!result.ok) return formatError(result.error);

  const d = result.data;
  const phaseLines = d.phases.map((p: PhaseExecutionInfo) => {
    const dur = p.duration_seconds > 0 ? ` · ${p.duration_seconds.toFixed(1)}s` : "";
    const cost = p.cost_usd !== "0" ? ` · $${p.cost_usd}` : "";
    return `  - **${p.name}** — ${p.status}${dur}${cost}`;
  });

  const rows: [string, string][] = [
    ["ID", d.workflow_execution_id],
    ["Workflow", d.workflow_id],
    ["Status", d.status],
    ["Tokens", `${d.total_tokens.toLocaleString()} (in: ${d.total_input_tokens.toLocaleString()}, out: ${d.total_output_tokens.toLocaleString()})`],
    ["Cost", `$${d.total_cost_usd}`],
    ["Duration", `${d.total_duration_seconds.toFixed(1)}s`],
  ];
  if (d.started_at) rows.push(["Started", d.started_at]);
  if (d.completed_at) rows.push(["Completed", d.completed_at]);
  if (d.error_message) rows.push(["Error", d.error_message]);

  const sections = [...buildMarkdownTable(`Execution: ${d.workflow_name}`, rows)];

  if (phaseLines.length > 0) {
    sections.push("", "### Phases", ...phaseLines);
  }

  if (d.artifact_ids.length > 0) {
    sections.push("", `### Artifacts: ${d.artifact_ids.join(", ")}`);
  }

  return { content: sections.join("\n") };
}
