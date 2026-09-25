/** Pass through canonical inventory evidence; relationship resolution remains server-owned. */
import type { SyntropicClient } from "../client.js";
import { formatError } from "../errors.js";

const kinds = ["node", "membership", "edge", "capture", "gap", "retraction", "binding"] as const;
export interface SessionInventoryArgs {
  execution_id: string;
  snapshot_id?: string;
  kind?: typeof kinds[number];
  cursor?: string;
  limit?: number;
}

function validBound(value: number | undefined, minimum: number, maximum = Number.MAX_SAFE_INTEGER): boolean {
  return value === undefined || (Number.isSafeInteger(value) && value >= minimum && value <= maximum);
}

function validatePage(args: SessionInventoryArgs): string | null {
  if (typeof args.snapshot_id !== "string" || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(args.snapshot_id)) {
    return "snapshot_id must be a UUID from the inventory response";
  }
  if (args.kind !== undefined && !kinds.includes(args.kind)) return "Unsupported inventory kind";
  if (args.cursor !== undefined && (typeof args.cursor !== "string" || args.cursor.length < 1 || args.cursor.length > 8192)) {
    return "cursor must be the next_cursor string from the previous page";
  }
  if (!validBound(args.limit, 1, 500)) return "limit must be an integer in 1..500";
  return null;
}

function pageQuery(args: SessionInventoryArgs): Record<string, string> {
  const query: Record<string, string> = { limit: String(args.limit ?? 100) };
  if (args.cursor !== undefined) query["cursor"] = args.cursor;
  return query;
}

export async function synGetSessionInventory(
  client: SyntropicClient,
  args: SessionInventoryArgs,
): Promise<{ content: string; isError?: true }> {
  if (typeof args.execution_id !== "string" || !args.execution_id.trim()) {
    return formatError(new Error("execution_id is required"));
  }
  const base = `/executions/${encodeURIComponent(args.execution_id)}/session-inventory`;
  if (args.snapshot_id === undefined) {
    if (args.kind !== undefined || args.cursor !== undefined || args.limit !== undefined) {
      return formatError(new Error("snapshot_id is required for page selectors"));
    }
    const result = await client.get<unknown>(base);
    return result.ok ? { content: JSON.stringify(result.data) } : formatError(result.error);
  }
  const invalid = validatePage(args);
  if (invalid) return formatError(new Error(invalid));
  const kind = args.kind ?? "node";
  const result = await client.get<unknown>(`${base}/${args.snapshot_id}/${kind}`, pageQuery(args));
  return result.ok ? { content: JSON.stringify(result.data) } : formatError(result.error);
}

export const sessionInventoryToolDefs = [{
  name: "syn_get_session_inventory",
  description: "Find all sessions associated with a workflow run, including reconstructed relationships, captures, and gaps. First omit snapshot_id to read reconstruction status and the committed snapshot. Then use that snapshot_id for bounded pages; pass next_cursor unchanged as cursor until null (a cursor is bound to one snapshot and section). Keep the same snapshot for every page. Coverage may be unknown or incomplete even when reconstruction is current. This read never schedules agents or reconstruction.",
  inputSchema: {
    type: "object" as const,
    additionalProperties: false,
    properties: {
      execution_id: { type: "string", description: "Workflow execution ID" },
      snapshot_id: { type: "string", format: "uuid", description: "Committed snapshot ID; omit to read current status" },
      kind: { type: "string", enum: kinds, description: "Inventory section (default node)" },
      cursor: { type: "string", minLength: 1, maxLength: 8192, description: "Previous page next_cursor; omit for the first page" },
      limit: { type: "integer", minimum: 1, maximum: 500, description: "Maximum records per page (default 100)" },
    },
    required: ["execution_id"],
  },
}] as const;
