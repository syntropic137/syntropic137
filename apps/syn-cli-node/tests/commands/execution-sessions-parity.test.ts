/**
 * Parity golden (#1398 row 9): replay the exchanges recorded from the real API
 * route by apps/syn-api/tests/test_session_inventory_parity.py and require the
 * CLI --json output to yield the digest the API test computed.
 */
import { readFileSync } from "node:fs";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { executionSessionsCommand } from "../../src/commands/execution-sessions.js";

interface Exchange { path: string; query: Record<string, string>; status: number; body: unknown }
interface Fixture {
  execution_id: string;
  phase_filter: string;
  exchanges: Exchange[];
  expected: Record<string, unknown>;
  expected_phase: { node_ids: string[] };
}
type Json = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

const fixture = JSON.parse(readFileSync(
  new URL("../../../syn-api/tests/fixtures/session_inventory_parity.json", import.meta.url), "utf8",
)) as Fixture;
const KINDS = ["node", "membership", "edge", "capture", "gap", "binding", "retraction"];

function serve(request: Request): Response {
  const url = new URL(request.url);
  const path = url.pathname.replace(/^\/api\/v1/, "");
  const query = Object.fromEntries([...url.searchParams].filter(([key]) => key !== "limit"));
  const match = fixture.exchanges.find(exchange => exchange.path === path
    && JSON.stringify(Object.entries(exchange.query).sort()) === JSON.stringify(Object.entries(query).sort()));
  if (!match) return new Response(JSON.stringify({ detail: `no fixture for ${path}` }), { status: 404 });
  return new Response(JSON.stringify(match.body), { status: match.status, headers: { "Content-Type": "application/json" } });
}

const namespace = (ref: Json) => (ref.harness == null ? ref.kind : `${ref.kind}:${ref.harness}`);

/** Same digest shape as _digest in the API test, derived only from CLI --json output. */
function digest(output: Json): Json {
  const items = (kind: string) => (output.pages as Json[]).filter(page => page.kind === kind).flatMap(page => page.items as Json[]);
  const refs = items("node").map(node => node.ref as Json);
  const namespaces: Record<string, number> = {};
  for (const ref of refs) namespaces[namespace(ref)] = (namespaces[namespace(ref)] ?? 0) + 1;
  return {
    revision: output.revision,
    snapshot_id: output.snapshot_id,
    coverage_state: output.coverage.state,
    complete: output.complete,
    counts: Object.fromEntries(KINDS.map(kind => [kind, output.counts[kind]])),
    traversed: Object.fromEntries(KINDS.map(kind => [kind, items(kind).length])),
    distinct_sessions: output.summary.distinct_sessions,
    platform_sessions: output.summary.platform_sessions,
    native_transcripts: output.summary.native_transcripts,
    invocations: output.summary.invocations,
    namespaces: Object.fromEntries(Object.entries(namespaces).sort()),
    node_ids: refs.map(ref => `${namespace(ref)}/${ref.local_id}`).sort(),
    gaps: (output.gaps as Json[]).map(gap => ({ reason: gap.reason, node_keys: [...(gap.node_keys ?? [])].sort() }))
      .sort((a, b) => { const x = JSON.stringify([a.reason, a.node_keys]), y = JSON.stringify([b.reason, b.node_keys]); return x < y ? -1 : x > y ? 1 : 0; }),
    counts_display: output.summary.counts_display,
    coverage_display: output.summary.coverage_display,
  };
}

const run = async (values: Record<string, unknown>): Promise<Json> => {
  vi.mocked(process.stdout.write).mockClear();
  await executionSessionsCommand.handler({ positionals: [fixture.execution_id], values: { json: true, all: true, ...values } });
  return JSON.parse(vi.mocked(process.stdout.write).mock.calls.map(c => String(c[0])).join(""));
};

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async (request: Request) => serve(request)));
  vi.spyOn(process.stdout, "write").mockReturnValue(true);
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("CLI --all --json agrees with the API on counts, coverage, revision, gaps and namespaces", async () => {
  expect(digest(await run({}))).toEqual(fixture.expected);
});

it("CLI --phase narrows to the same sessions the API returns for that phase", async () => {
  const output = await run({ phase: fixture.phase_filter });
  const ids = (output.pages as Json[]).filter(page => page.kind === "node")
    .flatMap(page => (page.items as Json[]).map(node => `${namespace(node.ref)}/${node.ref.local_id}`)).sort();
  expect(ids).toEqual(fixture.expected_phase.node_ids);
  expect(output.filters).toEqual({ phase_id: fixture.phase_filter });
});

it("--require-complete fails the fixture's open coverage", async () => {
  await expect(run({ "require-complete": true })).rejects.toThrow("coverage open");
});
