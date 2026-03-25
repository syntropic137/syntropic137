import type { SyntropicClient } from "../client.js";
import { formatError } from "../errors.js";
import type { OperationInfo, SessionDetail } from "../types.js";
import { buildMarkdownTable } from "./format.js";

// ---------------------------------------------------------------------------
// syn_get_session
// ---------------------------------------------------------------------------

export interface GetSessionArgs {
  session_id: string;
}

export async function synGetSession(
  client: SyntropicClient,
  args: GetSessionArgs,
): Promise<{ content: string; isError?: true }> {
  const result = await client.get<SessionDetail>(
    `/sessions/${encodeURIComponent(args.session_id)}`,
  );
  if (!result.ok) return formatError(result.error);

  const s = result.data;
  const rows: [string, string][] = [
    ["Status", s.status],
    ["Agent", `${s.agent_provider ?? "—"}${s.agent_model ? ` (${s.agent_model})` : ""}`],
    ["Tokens", `${s.total_tokens.toLocaleString()} (in: ${s.input_tokens.toLocaleString()}, out: ${s.output_tokens.toLocaleString()})`],
    ["Cost", `$${s.total_cost_usd}`],
  ];
  if (s.workflow_name) rows.push(["Workflow", s.workflow_name]);
  if (s.execution_id) rows.push(["Execution", s.execution_id]);
  if (s.duration_seconds != null) rows.push(["Duration", `${s.duration_seconds.toFixed(1)}s`]);
  if (s.error_message) rows.push(["Error", s.error_message]);

  const sections = [...buildMarkdownTable(`Session: ${s.id}`, rows)];
  sections.push(...formatOperations(s.operations));

  return { content: sections.join("\n") };
}

function formatToolOps(ops: OperationInfo[]): string[] {
  if (ops.length === 0) return [];
  const lines = ["", "**Tool calls:**"];
  for (const o of ops.slice(0, 20)) {
    const dur = o.duration_seconds != null ? ` (${o.duration_seconds.toFixed(1)}s)` : "";
    lines.push(`- ${o.tool_name} — ${o.success ? "✓" : "✗"}${dur}`);
  }
  if (ops.length > 20) lines.push(`  ... and ${ops.length - 20} more`);
  return lines;
}

function formatGitOps(ops: OperationInfo[]): string[] {
  if (ops.length === 0) return [];
  const lines = ["", "**Git operations:**"];
  for (const o of ops.slice(0, 10)) {
    lines.push(`- ${o.git_sha?.slice(0, 7)} ${o.git_message ?? ""}`);
  }
  return lines;
}

export function formatOperations(operations: OperationInfo[]): string[] {
  if (operations.length === 0) return [];

  return [
    "", "### Operations",
    ...formatToolOps(operations.filter((o) => o.tool_name)),
    ...formatGitOps(operations.filter((o) => o.git_sha)),
  ];
}
