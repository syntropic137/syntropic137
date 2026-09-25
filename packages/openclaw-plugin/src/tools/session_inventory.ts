/** Pass through canonical inventory evidence; relationship resolution remains server-owned. */
import type { ApiResult, SyntropicClient } from "../client.js";
import { formatError } from "../errors.js";
import type {
  InventoryFilter,
  InventoryGap,
  InventoryItem,
  InventoryKind,
  SessionInventoryPageResponse,
  SessionInventoryResponse,
} from "../types.js";

const kinds = ["node", "membership", "edge", "capture", "gap", "retraction", "binding"] as const satisfies readonly InventoryKind[];
/** Upper bound on pages one `all` call reads across every section. */
export const MAX_ALL_PAGES = 200;

export interface SessionInventoryArgs {
  execution_id: string;
  snapshot_id?: string;
  kind?: InventoryKind;
  cursor?: string;
  limit?: number;
  phase_id?: string;
  attempt_id?: string;
  node_key?: string;
  all?: boolean;
}

type ToolResult = { content: string; isError?: true };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const absent = (value: unknown): boolean => value === undefined;
const isString = (value: unknown): value is string => typeof value === "string";

function validFilter(value: unknown): boolean {
  return absent(value) || (isString(value) && value.trim().length > 0 && value.length <= 2048 && !value.includes("\0"));
}

/** Each selector's rule and the message returned when it fails. */
const selectorRules: ReadonlyArray<[(args: SessionInventoryArgs) => boolean, string]> = [
  [a => absent(a.snapshot_id) || (isString(a.snapshot_id) && UUID.test(a.snapshot_id)), "snapshot_id must be a UUID from the inventory response"],
  [a => absent(a.kind) || kinds.includes(a.kind as InventoryKind), "Unsupported inventory kind"],
  [a => absent(a.cursor) || (isString(a.cursor) && a.cursor.length >= 1 && a.cursor.length <= 8192), "cursor must be the next_cursor string from the previous page"],
  [a => absent(a.limit) || (Number.isSafeInteger(a.limit) && a.limit! >= 1 && a.limit! <= 500), "limit must be an integer in 1..500"],
  [a => validFilter(a.phase_id), "phase_id must be a non-blank string of at most 2048 characters"],
  [a => validFilter(a.attempt_id), "attempt_id must be a non-blank string of at most 2048 characters"],
  [a => absent(a.node_key) || (isString(a.node_key) && /^[a-f0-9]{64}$/.test(a.node_key)), "node_key must be a 64-character hex key from item_keys"],
  [a => absent(a.all) || typeof a.all === "boolean", "all must be a boolean"],
];

function validateSelectors(args: SessionInventoryArgs): string | null {
  return selectorRules.find(([valid]) => !valid(args))?.[1] ?? null;
}

function pageQuery(limit: number | undefined, cursor: string | undefined, args: SessionInventoryArgs): Record<string, string> {
  const query: Record<string, string> = { limit: String(limit ?? 100) };
  if (cursor !== undefined) query["cursor"] = cursor;
  if (args.phase_id !== undefined) query["phase_id"] = args.phase_id;
  if (args.attempt_id !== undefined) query["attempt_id"] = args.attempt_id;
  return query;
}

function filtersOf(args: SessionInventoryArgs): InventoryFilter {
  const filters: InventoryFilter = {};
  if (args.phase_id !== undefined) filters.phase_id = args.phase_id;
  if (args.attempt_id !== undefined) filters.attempt_id = args.attempt_id;
  return filters;
}

const json = (value: unknown): ToolResult => ({ content: JSON.stringify(value) });
const fail = (message: string): ToolResult => formatError(new Error(message));
const passThrough = <T>(result: ApiResult<T>): ToolResult => result.ok ? json(result.data) : formatError(result.error);

interface SectionResult {
  items: InventoryItem[];
  /** Resume point when the page budget stopped this section early; null when fully read. */
  next_cursor: string | null;
  truncated: boolean;
  body_overrides: SessionInventoryPageResponse["body_overrides"];
}

interface Traversal {
  client: SyntropicClient;
  base: string;
  snapshotId: string;
  args: SessionInventoryArgs;
  budget: { pages: number };
  snapshot: SessionInventoryPageResponse["snapshot"] | null;
}

type PageOutcome = { next: string | null } | { error: ToolResult };

async function readPage(t: Traversal, kind: InventoryKind, cursor: string | undefined, section: SectionResult): Promise<PageOutcome> {
  const page: ApiResult<SessionInventoryPageResponse> = await t.client.get<SessionInventoryPageResponse>(
    `${t.base}/${t.snapshotId}/${kind}`, pageQuery(t.args.limit ?? 500, cursor, t.args));
  if (!page.ok) return { error: formatError(page.error) };
  if (page.data.snapshot.snapshot_id !== t.snapshotId || page.data.kind !== kind) {
    return { error: fail("Inventory response belongs to another revision or section") };
  }
  t.snapshot = page.data.snapshot;
  section.items.push(...page.data.items);
  section.body_overrides.push(...(page.data.body_overrides ?? []));
  const next = page.data.next_cursor ?? null;
  if (next !== null && next === cursor) return { error: fail("Inventory cursor did not advance") };
  return { next };
}

/** Every page of one section until done or the shared page budget runs out. */
async function readSection(t: Traversal, kind: InventoryKind): Promise<SectionResult | ToolResult> {
  const section: SectionResult = { items: [], next_cursor: null, truncated: false, body_overrides: [] };
  let cursor: string | undefined = t.args.kind === kind ? t.args.cursor : undefined;
  for (;;) {
    if (t.budget.pages === 0) return { ...section, truncated: true, next_cursor: cursor ?? null };
    t.budget.pages -= 1;
    const outcome = await readPage(t, kind, cursor, section);
    if ("error" in outcome) return outcome.error;
    if (outcome.next === null) return section;
    cursor = outcome.next;
  }
}

/**
 * Every page of every requested section of ONE pinned revision. The page
 * budget bounds work; a truncated section keeps its cursor so the caller can
 * resume, and gaps are returned alongside so partial coverage stays visible.
 */
async function readAll(client: SyntropicClient, base: string, args: SessionInventoryArgs): Promise<ToolResult> {
  const status = await client.get<SessionInventoryResponse>(base);
  if (!status.ok) return formatError(status.error);
  const head = {
    reconstruction_status: status.data.reconstruction_status,
    later_evidence_pending: status.data.later_evidence_pending,
    summary: status.data.summary,
    filters: filtersOf(args),
  };
  const snapshotId = args.snapshot_id ?? status.data.snapshot?.snapshot_id;
  if (snapshotId === undefined) {
    // No published revision: say so, never an empty inventory.
    return json({ ...head, snapshot_id: null, revision: null, coverage: null, counts: null, sections: {}, gaps: null });
  }
  const t: Traversal = { client, base, snapshotId, args, budget: { pages: MAX_ALL_PAGES }, snapshot: null };
  const sections: Partial<Record<InventoryKind, SectionResult>> = {};
  for (const kind of args.kind !== undefined ? [args.kind] : [...kinds]) {
    const section = await readSection(t, kind);
    if ("content" in section) return section;
    sections[kind] = section;
  }
  const pinned = t.snapshot ?? status.data.snapshot;
  const gaps = sections.gap && !sections.gap.truncated ? (sections.gap.items as InventoryGap[]) : null;
  return json({
    ...head,
    snapshot_id: snapshotId,
    revision: pinned?.revision ?? null,
    coverage: pinned?.coverage ?? null,
    counts: pinned?.counts ?? null,
    sections,
    gaps,
  });
}

const anyDefined = (...values: unknown[]): boolean => values.some(value => value !== undefined);

function allModeConflict(args: SessionInventoryArgs): string | null {
  if (args.node_key !== undefined) return "node_key cannot be combined with all";
  if (args.cursor !== undefined && args.kind === undefined) return "cursor requires kind";
  if (args.cursor !== undefined && args.snapshot_id === undefined) return "cursor requires snapshot_id";
  return null;
}

async function readStatus(client: SyntropicClient, base: string, args: SessionInventoryArgs): Promise<ToolResult> {
  if (anyDefined(args.kind, args.cursor, args.limit, args.phase_id, args.attempt_id, args.node_key)) {
    return fail("snapshot_id is required for page selectors");
  }
  return passThrough(await client.get<SessionInventoryResponse>(base));
}

async function lookupNode(client: SyntropicClient, base: string, snapshotId: string, args: SessionInventoryArgs): Promise<ToolResult> {
  if (anyDefined(args.kind, args.cursor, args.limit, args.phase_id, args.attempt_id)) {
    return fail("node_key lookup takes only snapshot_id");
  }
  return passThrough(await client.get<unknown>(`${base}/${snapshotId}/nodes/${args.node_key}`));
}

async function readOnePage(client: SyntropicClient, base: string, snapshotId: string, args: SessionInventoryArgs): Promise<ToolResult> {
  const kind = args.kind ?? "node";
  return passThrough(await client.get<SessionInventoryPageResponse>(`${base}/${snapshotId}/${kind}`, pageQuery(args.limit, args.cursor, args)));
}

async function dispatch(client: SyntropicClient, base: string, args: SessionInventoryArgs): Promise<ToolResult> {
  if (args.all === true) {
    const conflict = allModeConflict(args);
    return conflict ? fail(conflict) : readAll(client, base, args);
  }
  if (args.snapshot_id === undefined) return readStatus(client, base, args);
  if (args.node_key !== undefined) return lookupNode(client, base, args.snapshot_id, args);
  return readOnePage(client, base, args.snapshot_id, args);
}

export async function synGetSessionInventory(client: SyntropicClient, args: SessionInventoryArgs): Promise<ToolResult> {
  if (typeof args.execution_id !== "string" || !args.execution_id.trim()) return fail("execution_id is required");
  const invalid = validateSelectors(args);
  if (invalid) return fail(invalid);
  return dispatch(client, `/executions/${encodeURIComponent(args.execution_id)}/session-inventory`, args);
}

export const sessionInventoryToolDefs = [{
  name: "syn_get_session_inventory",
  description: "Find all sessions associated with a workflow run, including reconstructed relationships, captures, and gaps. Omit snapshot_id to read reconstruction status, the committed snapshot and `summary` (server-derived counts per identity namespace, coverage and `complete`). Set all=true to read every section (or only `kind`) and every page of one pinned revision in one call; gaps and per-section truncation cursors are returned. Otherwise use snapshot_id for bounded pages and pass next_cursor unchanged as cursor until null (a cursor is bound to one snapshot, section and filter set). phase_id/attempt_id narrow to sessions with a matching membership. node_key (from item_keys) resolves an edge endpoint that lives on another page. Native transcript ids are harness-scoped and are never platform session ids. Coverage may be open, unknown, missing or unsupported even when reconstruction is current; only summary.complete means complete. This read never schedules agents or reconstruction.",
  inputSchema: {
    type: "object" as const,
    additionalProperties: false,
    properties: {
      execution_id: { type: "string", description: "Workflow execution ID" },
      snapshot_id: { type: "string", format: "uuid", description: "Committed snapshot ID; omit to read current status (or, with all, to pin the current head)" },
      kind: { type: "string", enum: kinds, description: "Inventory section (default node; with all, restricts to one section)" },
      cursor: { type: "string", minLength: 1, maxLength: 8192, description: "Previous page next_cursor; omit for the first page" },
      limit: { type: "integer", minimum: 1, maximum: 500, description: "Maximum records per page (default 100, or 500 with all)" },
      phase_id: { type: "string", minLength: 1, maxLength: 2048, description: "Only sessions with a membership in this phase" },
      attempt_id: { type: "string", minLength: 1, maxLength: 2048, description: "Only sessions with a membership in this attempt" },
      node_key: { type: "string", pattern: "^[a-f0-9]{64}$", description: "Resolve one node by its item_keys key within snapshot_id" },
      all: { type: "boolean", description: `Traverse every page of the pinned revision (bounded to ${MAX_ALL_PAGES} pages)` },
    },
    required: ["execution_id"],
  },
}] as const;
