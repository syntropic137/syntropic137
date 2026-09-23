/** Read published session inventory without triggering capture or reconstruction. */
import { randomUUID } from "node:crypto";
import type { components } from "../generated/api-types.js";
import { z } from "zod";
import { api, unwrap } from "../client/typed.js";
import type { CommandDef } from "../framework/command.js";
import { CLIError } from "../framework/errors.js";
import { print } from "../output/console.js";

const kindSchema = z.enum(["node", "membership", "edge", "capture", "gap", "binding", "retraction"]);

const cursorSchema = z.object({
  execution: z.string(), source: z.string(), snapshot: z.string().uuid(),
  after: z.number().int().nonnegative(), kind: kindSchema.default("node"),
}).strict();

export const executionSessionsCommand: CommandDef = {
  name: "sessions",
  description: "Read the reconstructed session inventory for a workflow run",
  args: [{ name: "execution-id", description: "Execution ID", required: true }],
  options: {
    refresh: { type: "boolean", description: "Schedule durable local reconstruction and report its job" },
    "idempotency-key": { type: "string", description: "Reuse a refresh request key when retrying" },
    json: { type: "boolean", description: "Print metadata and revision-pinned pages as JSON" },
    kind: { type: "string", description: "Inventory section: node, membership, edge, capture, gap, binding, retraction (default node)" },
    all: { type: "boolean", description: "Read every page of the selected section from one revision" },
    limit: { type: "string", default: "100", description: "Items per page (1 to 500)" },
    cursor: { type: "string", description: "Continue a previously returned inventory cursor" },
    "require-complete": { type: "boolean", description: "Fail unless coverage is reconciled and current" },
  },
  handler: async ({ positionals, values }) => {
    const execution = positionals[0];
    if (!execution) throw new CLIError("execution-id is required");
    const limit = Number(values["limit"] ?? "100");
    if (!Number.isInteger(limit) || limit < 1 || limit > 500) {
      throw new CLIError("limit must be an integer between 1 and 500");
    }
    let cursor: z.infer<typeof cursorSchema> | undefined;
    if (values["cursor"] !== undefined) {
      try {
        cursor = cursorSchema.parse(JSON.parse(Buffer.from(String(values["cursor"]), "base64url").toString("utf8")));
      } catch { throw new CLIError("Invalid inventory cursor"); }
    }
    const selected = kindSchema.safeParse(values["kind"] ?? cursor?.kind ?? "node");
    if (!selected.success) throw new CLIError("Invalid inventory kind");
    const kind = selected.data;
    if (cursor && cursor.kind !== kind) throw new CLIError("Inventory cursor belongs to another section");
    let refresh: components["schemas"]["SessionInventoryJobResponse"] | null = null;
    if (values["idempotency-key"] && values["refresh"] !== true) throw new CLIError("idempotency-key requires --refresh");
    if (values["refresh"] === true) {
      if (cursor) throw new CLIError("refresh cannot be combined with a historical cursor");
      const scheduled = unwrap(await api.POST("/executions/{execution_id}/session-inventory/reconcile", {
        params: { path: { execution_id: execution } },
        body: { idempotency_key: String(values["idempotency-key"] ?? randomUUID()) },
      }), "Failed to schedule inventory refresh");
      refresh = unwrap(await api.GET("/session-inventory-jobs/{job_id}", {
        params: { path: { job_id: scheduled.job_id } },
      }), "Failed to read inventory job");
      if (values["json"] !== true) print(`Refresh job: ${refresh.job_id}; status: ${refresh.stage}`);
    }
    const status = unwrap(await api.GET("/executions/{execution_id}/session-inventory", {
      params: { path: { execution_id: execution } },
    }), "Failed to read session inventory");
    if (cursor && (cursor.execution !== status.run.execution_id || cursor.source !== status.run.source_instance_id)) {
      throw new CLIError("Inventory cursor belongs to another run or installation");
    }
    const snapshotId = cursor?.snapshot ?? status.snapshot?.snapshot_id;
    const json = values["json"] === true;
    if (json) process.stdout.write(`{"status":${JSON.stringify(status)},"refresh":${JSON.stringify(refresh)},"pages":[`);
    else print(`Reconstruction: ${status.reconstruction_status}; coverage: ${status.snapshot?.coverage.state ?? "unknown"}`);
    let after = cursor?.after ?? -1;
    let nextCursor: string | null = null;
    let first = true;
    let complete = false;
    if (snapshotId) {
      do {
        const page: components["schemas"]["SessionInventoryPageResponse"] = unwrap(await api.GET("/executions/{execution_id}/session-inventory/{snapshot_id}/{kind}", {
          params: { path: { execution_id: status.run.execution_id, snapshot_id: snapshotId, kind }, query: { after, limit } },
        }), "Failed to read inventory page");
        if (page.kind !== kind) throw new CLIError("Inventory response belongs to another section");
        if (page.snapshot.run.source_instance_id !== status.run.source_instance_id || page.snapshot.run.execution_id !== status.run.execution_id) throw new CLIError("Inventory response belongs to another run or installation");
        if (page.snapshot.snapshot_id !== snapshotId) throw new CLIError("Inventory revision changed during pagination");
        complete = page.snapshot.coverage.state === "reconciled"
          && status.reconstruction_status === "current"
          && status.snapshot?.snapshot_id === snapshotId;
        if (json) process.stdout.write(`${first ? "" : ","}${JSON.stringify(page)}`);
        else {
          if (first) print(`Revision: ${page.snapshot.revision}; coverage: ${page.snapshot.coverage.state}; nodes: ${page.snapshot.counts.node}; gaps: ${page.snapshot.counts.gap}`);
          printInventoryItems(page);
        }
        first = false;
        const next = page.next_after;
        if (next == null) { nextCursor = null; break; }
        if (next <= after) throw new CLIError("Inventory cursor did not advance");
        after = next;
        nextCursor = Buffer.from(JSON.stringify({ execution: status.run.execution_id, source: status.run.source_instance_id, snapshot: snapshotId, after, kind })).toString("base64url");
      } while (values["all"] === true);
    }
    if (json) process.stdout.write(`],"next_cursor":${JSON.stringify(nextCursor)}}\n`);
    else if (nextCursor) print(`More sessions: --cursor ${nextCursor}`);
    if (values["require-complete"] === true && !complete) {
      throw new CLIError("Session inventory coverage is not reconciled and current");
    }
  },
};


function printInventoryItems(page: components["schemas"]["SessionInventoryPageResponse"]): void {
  for (const item of page.items) {
    if (page.kind === "node") {
      if (!("ref" in item)) throw new CLIError("Invalid node inventory page");
      print(`${item.ref.kind}\t${item.ref.harness ?? ""}\t${item.ref.local_id}`);
    } else if (page.kind === "capture") {
      if (!("availability" in item)) throw new CLIError("Invalid capture inventory page");
      const current = item.destination === "local"
        ? page.body_overrides?.find(state => state.archive_sha256 === item.archived_byte_hash)?.status
        : undefined;
      print(`${item.node.harness ?? ""}\t${item.node.local_id}\t${item.destination}: recorded=${item.availability}; current=${current ?? "unchecked"}`);
      if (item.archived_byte_hash) print(`Archive: ${item.archived_byte_hash}`);
    } else {
      print(JSON.stringify(item));
    }
  }
}
