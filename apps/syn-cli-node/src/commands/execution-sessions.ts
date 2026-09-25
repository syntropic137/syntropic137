/** Read published session inventory without triggering capture or reconstruction. */
import { randomUUID } from "node:crypto";
import type { components } from "../generated/api-types.js";
import { z } from "zod";
import { api, unwrap } from "../client/typed.js";
import type { CommandDef } from "../framework/command.js";
import { CLIError } from "../framework/errors.js";
import { print } from "../output/console.js";
import { renderInventory, renderItems } from "./execution-sessions-view.js";

const KINDS = ["node", "membership", "edge", "capture", "gap", "binding", "retraction"] as const;
const kindSchema = z.enum(KINDS);
type Kind = z.infer<typeof kindSchema>;
type Status = components["schemas"]["SessionInventoryResponse"];
type Page = components["schemas"]["SessionInventoryPageResponse"];
type Snapshot = components["schemas"]["InventorySnapshot"];
type Filters = { phase_id?: string; attempt_id?: string };

// Upper bound on pages one invocation reads, so a server that never ends a
// traversal cannot keep the CLI running forever. 500 items x 10k pages.
const MAX_PAGES = 10_000;

// CLI envelope: the snapshot selects the pinned route; `server` is the API's
// opaque cursor, which the API itself binds to scope, revision, section and filters.
const cursorSchema = z.object({
  execution: z.string(), source: z.string(), snapshot: z.string().uuid(),
  server: z.string().min(1), kind: kindSchema.default("node"),
  phase: z.string().min(1).optional(), attempt: z.string().min(1).optional(),
}).strict();
type Cursor = z.infer<typeof cursorSchema>;

function parseCursor(raw: unknown): Cursor | undefined {
  if (raw === undefined) return undefined;
  try {
    return cursorSchema.parse(JSON.parse(Buffer.from(String(raw), "base64url").toString("utf8")));
  } catch { throw new CLIError("Invalid inventory cursor"); }
}

function filterValue(raw: unknown, name: string): string | undefined {
  if (raw === undefined) return undefined;
  const value = String(raw);
  if (!value.trim() || value.length > 2048 || value.includes("\0")) throw new CLIError(`Invalid --${name} value`);
  return value;
}

function resolveFilters(values: Record<string, unknown>, cursor: Cursor | undefined): Filters {
  const phase = filterValue(values["phase"], "phase");
  const attempt = filterValue(values["attempt"], "attempt");
  if (cursor && ((phase !== undefined && phase !== cursor.phase) || (attempt !== undefined && attempt !== cursor.attempt))) {
    throw new CLIError("Inventory cursor belongs to other --phase/--attempt filters");
  }
  const filters: Filters = {};
  const selectedPhase = phase ?? cursor?.phase;
  const selectedAttempt = attempt ?? cursor?.attempt;
  if (selectedPhase !== undefined) filters.phase_id = selectedPhase;
  if (selectedAttempt !== undefined) filters.attempt_id = selectedAttempt;
  return filters;
}

/** Page errors carry a structured cursor detail; surface its message and restart hint. */
function pageError(error: unknown, response: Response | undefined): CLIError {
  const detail = typeof error === "object" && error !== null && "detail" in error ? (error as { detail: unknown }).detail : undefined;
  if (typeof detail === "object" && detail !== null && "code" in detail) {
    const cursorError = detail as components["schemas"]["SessionInventoryCursorError"];
    const hint = cursorError.restart ? "; rerun without --cursor to read the current revision" : "";
    return new CLIError(`Failed to read inventory page: ${cursorError.code}: ${cursorError.message}${hint}`);
  }
  const text = typeof detail === "string" ? detail : `request failed with ${response?.status ?? "unknown status"}`;
  return new CLIError(`Failed to read inventory page: ${text}`);
}

async function readPage(
  status: Status, snapshotId: string, kind: Kind, limit: number, filters: Filters, server: string | undefined,
): Promise<Page> {
  const query = { limit, ...filters, ...(server === undefined ? {} : { cursor: server }) };
  const result = await api.GET("/executions/{execution_id}/session-inventory/{snapshot_id}/{kind}", {
    params: { path: { execution_id: status.run.execution_id, snapshot_id: snapshotId, kind }, query },
  });
  if (result.error !== undefined || !result.response.ok) throw pageError(result.error, result.response);
  const page = result.data!;
  if (page.kind !== kind) throw new CLIError("Inventory response belongs to another section");
  if (page.snapshot.run.source_instance_id !== status.run.source_instance_id || page.snapshot.run.execution_id !== status.run.execution_id) {
    throw new CLIError("Inventory response belongs to another run or installation");
  }
  if (page.snapshot.snapshot_id !== snapshotId) throw new CLIError("Inventory revision changed during pagination");
  return page;
}

interface Traversal {
  pinned: Snapshot | null;
  gaps: Page["items"] | null;
  nextCursor: string | null;
  pages: Page[];
}

interface Plan {
  status: Status;
  snapshotId: string;
  kinds: readonly Kind[];
  everyPage: boolean;
  limit: number;
  filters: Filters;
  server: string | undefined;
  onPage: (page: Page) => void;
  keepPages: boolean;
}

interface ReadState { budget: number; pinned: Snapshot | null; pages: Page[] }

async function nextPage(plan: Plan, kind: Kind, server: string | undefined, state: ReadState): Promise<Page> {
  if (state.budget-- <= 0) throw new CLIError(`Inventory traversal exceeded ${MAX_PAGES} pages`);
  const page = await readPage(plan.status, plan.snapshotId, kind, plan.limit, plan.filters, server);
  state.pinned = page.snapshot;
  plan.onPage(page);
  if (plan.keepPages) state.pages.push(page);
  return page;
}

/** The CLI cursor envelope around the server's opaque cursor, carrying section and filters. */
function continuation(plan: Plan, kind: Kind, server: string): string {
  const envelope: Cursor = {
    execution: plan.status.run.execution_id, source: plan.status.run.source_instance_id,
    snapshot: plan.snapshotId, server, kind,
    ...(plan.filters.phase_id === undefined ? {} : { phase: plan.filters.phase_id }),
    ...(plan.filters.attempt_id === undefined ? {} : { attempt: plan.filters.attempt_id }),
  };
  return Buffer.from(JSON.stringify(envelope)).toString("base64url");
}

interface SectionRead { gaps: Page["items"]; nextCursor: string | null }

async function readSection(plan: Plan, kind: Kind, start: string | undefined, state: ReadState): Promise<SectionRead> {
  const gaps: Page["items"] = [];
  let server = start;
  for (;;) {
    const page = await nextPage(plan, kind, server, state);
    if (kind === "gap") gaps.push(...page.items);
    const next = page.next_cursor ?? null;
    if (next === null) return { gaps, nextCursor: null };
    if (next === server) throw new CLIError("Inventory cursor did not advance");
    if (!plan.everyPage) return { gaps, nextCursor: continuation(plan, kind, next) };
    server = next;
  }
}

async function traverse(plan: Plan): Promise<Traversal> {
  const state: ReadState = { budget: MAX_PAGES, pinned: null, pages: [] };
  const result: Traversal = { pinned: null, gaps: null, nextCursor: null, pages: state.pages };
  for (const [index, kind] of plan.kinds.entries()) {
    const section = await readSection(plan, kind, index === 0 ? plan.server : undefined, state);
    result.nextCursor = section.nextCursor;
    // Gaps are reported only when the gap section was read from its start to
    // its end; a partial list must never look like the complete set.
    const whole = section.nextCursor === null && plan.server === undefined;
    if (kind === "gap" && whole) result.gaps = section.gaps;
  }
  result.pinned = state.pinned;
  return result;
}

async function scheduleRefresh(execution: string, key: unknown): Promise<components["schemas"]["SessionInventoryJobResponse"]> {
  const scheduled = unwrap(await api.POST("/executions/{execution_id}/session-inventory/reconcile", {
    params: { path: { execution_id: execution } },
    // The CLI refresh stays live-only; historical backfill is an explicit API call.
    body: { idempotency_key: String(key ?? randomUUID()), include_history: false },
  }), "Failed to schedule inventory refresh");
  return unwrap(await api.GET("/session-inventory-jobs/{job_id}", {
    params: { path: { job_id: scheduled.job_id } },
  }), "Failed to read inventory job");
}

function printHeader(status: Status): void {
  const summary = status.summary;
  print(`Execution: ${status.run.execution_id} (source ${status.run.source_instance_id})`);
  if (status.snapshot) print(`Revision: ${status.snapshot.revision} (snapshot ${status.snapshot.snapshot_id})`);
  print(`Reconstruction: ${status.reconstruction_status}${status.later_evidence_pending ? " (newer evidence awaiting reconstruction)" : ""}`);
  print(`Coverage: ${summary.coverage_display}`);
  print(`Sessions: ${summary.counts_display}`);
  print(`Remote replication: ${summary.remote_replication}`);
}

export const executionSessionsCommand: CommandDef = {
  name: "sessions",
  description: "List every session of a workflow run: platform sessions, invocations and native transcripts, with lineage, gaps and coverage",
  args: [{ name: "execution-id", description: "Execution ID", required: true }],
  options: {
    refresh: { type: "boolean", description: "Schedule durable local reconstruction and report its job" },
    "idempotency-key": { type: "string", description: "Reuse a refresh request key when retrying" },
    json: { type: "boolean", description: "Print summary, revision, counts, coverage, gaps, pages and next cursor as JSON" },
    kind: { type: "string", description: "Inventory section: node, membership, edge, capture, gap, binding, retraction (default node; --all reads every section)" },
    all: { type: "boolean", description: "Read every page of every section (or of --kind) from one pinned revision" },
    phase: { type: "string", description: "Only sessions with a membership in this phase ID" },
    attempt: { type: "string", description: "Only sessions with a membership in this attempt ID" },
    limit: { type: "string", default: "100", description: "Items per page (1 to 500)" },
    cursor: { type: "string", description: "Continue a previously returned inventory cursor" },
    "require-complete": { type: "boolean", description: "Exit nonzero unless coverage is reconciled and the revision is current" },
  },
  handler: async ({ positionals, values }) => {
    const execution = positionals[0];
    if (!execution) throw new CLIError("execution-id is required");
    const limit = Number(values["limit"] ?? "100");
    if (!Number.isInteger(limit) || limit < 1 || limit > 500) {
      throw new CLIError("limit must be an integer between 1 and 500");
    }
    const cursor = parseCursor(values["cursor"]);
    const everyPage = values["all"] === true;
    const selected = kindSchema.safeParse(values["kind"] ?? cursor?.kind ?? "node");
    if (!selected.success) throw new CLIError("Invalid inventory kind");
    if (cursor && values["kind"] !== undefined && cursor.kind !== selected.data) throw new CLIError("Inventory cursor belongs to another section");
    const kinds: readonly Kind[] = everyPage && values["kind"] === undefined && !cursor ? KINDS : [selected.data];
    const filters = resolveFilters(values, cursor);
    if (values["idempotency-key"] && values["refresh"] !== true) throw new CLIError("idempotency-key requires --refresh");
    const json = values["json"] === true;
    let refresh: components["schemas"]["SessionInventoryJobResponse"] | null = null;
    if (values["refresh"] === true) {
      if (cursor) throw new CLIError("refresh cannot be combined with a historical cursor");
      refresh = await scheduleRefresh(execution, values["idempotency-key"]);
      if (!json) print(`Refresh job: ${refresh.job_id}; status: ${refresh.stage}`);
    }
    const status = unwrap(await api.GET("/executions/{execution_id}/session-inventory", {
      params: { path: { execution_id: execution } },
    }), "Failed to read session inventory");
    if (cursor && (cursor.execution !== status.run.execution_id || cursor.source !== status.run.source_instance_id)) {
      throw new CLIError("Inventory cursor belongs to another run or installation");
    }
    const snapshotId = cursor?.snapshot ?? status.snapshot?.snapshot_id;
    // A joined human view needs every section; single sections print as they stream.
    const joinedView = !json && kinds.length === KINDS.length;
    if (json) {
      process.stdout.write(`{"status":${JSON.stringify(status)},"refresh":${JSON.stringify(refresh)},"summary":${JSON.stringify(status.summary)},"filters":${JSON.stringify(filters)},"pages":[`);
    } else printHeader(status);
    let first = true;
    const traversal: Traversal = snapshotId
      ? await traverse({
        status, snapshotId, kinds, everyPage, limit, filters, server: cursor?.server, keepPages: joinedView,
        onPage: page => {
          if (json) process.stdout.write(`${first ? "" : ","}${JSON.stringify(page)}`);
          else if (!joinedView) for (const line of renderItems(page, status.summary.remote_replication)) print(line);
          first = false;
        },
      })
      : { pinned: null, gaps: null, nextCursor: null, pages: [] };
    const pinned = traversal.pinned ?? status.snapshot ?? null;
    // Complete only for the current head: a cursor into an older revision is never complete.
    const complete = status.summary.complete && pinned !== null && status.snapshot?.snapshot_id === pinned.snapshot_id;
    if (json) {
      process.stdout.write(`],"snapshot_id":${JSON.stringify(pinned?.snapshot_id ?? null)},"revision":${JSON.stringify(pinned?.revision ?? null)},"coverage":${JSON.stringify(pinned?.coverage ?? null)},"counts":${JSON.stringify(pinned?.counts ?? null)},"gaps":${JSON.stringify(traversal.gaps)},"next_cursor":${JSON.stringify(traversal.nextCursor)},"complete":${JSON.stringify(complete)}}\n`);
    } else {
      if (joinedView) for (const line of renderInventory(traversal.pages, status.summary.remote_replication)) print(line);
      if (!status.snapshot && !cursor) print("No published inventory yet.");
      if (traversal.nextCursor) print(`More results: --cursor ${traversal.nextCursor}`);
      else if (!everyPage && status.snapshot) print(`Full inventory: ${status.summary.follow_up_command}`);
    }
    if (values["require-complete"] === true && !complete) {
      throw new CLIError(`Session inventory is not complete (coverage ${status.summary.coverage_state}, reconstruction ${status.reconstruction_status})`);
    }
  },
};
