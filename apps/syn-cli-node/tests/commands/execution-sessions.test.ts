import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { executionSessionsCommand } from "../../src/commands/execution-sessions.js";

const fetchMock = vi.fn();
const run = { source_instance_id: "installation", execution_id: "execution" };
const snapshot = {
  snapshot_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", run, revision: "revision",
  resolver_version: "test/1", evidence_watermark: 3,
  coverage: { state: "unknown" }, counts: { node: 2, gap: 1 },
};
const summary = {
  complete: false, coverage_state: "unknown", coverage_display: "unknown: no completeness contract for this run",
  revision: "revision", distinct_sessions: 2, platform_sessions: 0, invocations: 0, native_transcripts: 2, gaps: 1,
  namespaces: [], counts_display: "0 platform sessions, 2 native transcripts (fake 2), 0 invocations, 1 gap",
  remote_replication: "enabled", follow_up_command: "syn execution sessions execution --all",
};
const status = { run, snapshot, reconstruction_status: "current", later_evidence_pending: false, observed_evidence_watermark: 3, summary };
const page = (id: string, next: string | null, kind = "node") => ({
  snapshot, kind, filters: {}, item_keys: [{ node_key: "k".repeat(64) }],
  items: kind === "node" ? [{ ref: { kind: "transcript", local_id: id, harness: "fake", source_instance_id: "installation" } }] : [],
  next_cursor: next,
});
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const output = () => vi.mocked(process.stdout.write).mock.calls.map(c => String(c[0])).join("");
const urls = () => fetchMock.mock.calls.map(c => new URL((c[0] as Request).url));

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  vi.spyOn(process.stdout, "write").mockReturnValue(true);
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("streams every page of one section from the original revision with full native IDs", async () => {
  fetchMock.mockResolvedValueOnce(response(status))
    .mockResolvedValueOnce(response(page("native-one-full-id", "server-cursor-1")))
    .mockResolvedValueOnce(response(page("native-two-full-id", null)));
  await executionSessionsCommand.handler({ positionals: ["execution"], values: { all: true, kind: "node", json: true, limit: "1" } });
  const result = JSON.parse(output());
  expect(result.pages).toHaveLength(2);
  expect(result.pages[1].items[0].ref.local_id).toBe("native-two-full-id");
  expect(result.next_cursor).toBeNull();
  expect(result.gaps).toBeNull(); // gap section not read: never an empty-looking list
  const [, first, second] = urls();
  expect(first!.pathname).toContain(snapshot.snapshot_id);
  expect(second!.pathname).toContain(snapshot.snapshot_id);
  expect(first!.searchParams.get("cursor")).toBeNull();
  expect(second!.searchParams.get("cursor")).toBe("server-cursor-1");
  expect(second!.searchParams.get("after")).toBeNull();
});

it("--all traverses every section and reports revision, counts, coverage, gaps and summary", async () => {
  const gap = { reason: "unlinked_native_transcript", node_keys: ["k".repeat(64)], evidence_ids: [] };
  fetchMock.mockImplementation(async (request: Request) => {
    const url = new URL(request.url);
    if (url.pathname.endsWith("/session-inventory")) return response(status);
    const kind = url.pathname.split("/").pop()!;
    if (kind === "node" && !url.searchParams.get("cursor")) return response(page("native-a", "n2"));
    if (kind === "node") return response(page("native-b", null));
    if (kind === "gap") return response({ ...page("", null, "gap"), items: [gap], item_keys: [{}] });
    return response(page("", null, kind));
  });
  await executionSessionsCommand.handler({ positionals: ["execution"], values: { all: true, json: true } });
  const result = JSON.parse(output());
  const kinds = urls().slice(1).map(url => url.pathname.split("/").pop());
  expect(kinds).toEqual(["node", "node", "membership", "edge", "capture", "gap", "binding", "retraction"]);
  expect(result.revision).toBe("revision");
  expect(result.snapshot_id).toBe(snapshot.snapshot_id);
  expect(result.counts).toEqual(snapshot.counts);
  expect(result.coverage).toEqual({ state: "unknown" });
  expect(result.summary).toEqual(summary);
  expect(result.gaps).toEqual([gap]);
  expect(result.complete).toBe(false);
  expect(result.next_cursor).toBeNull();
});

it("maps --phase/--attempt to API filters and binds them into the continuation cursor", async () => {
  fetchMock.mockResolvedValueOnce(response(status)).mockResolvedValueOnce(response(page("native", "server-next")));
  await executionSessionsCommand.handler({ positionals: ["execution"], values: { json: true, phase: "phase-plan", attempt: "attempt-1" } });
  const pageUrl = urls()[1]!;
  expect(pageUrl.searchParams.get("phase_id")).toBe("phase-plan");
  expect(pageUrl.searchParams.get("attempt_id")).toBe("attempt-1");
  const result = JSON.parse(output());
  expect(result.filters).toEqual({ phase_id: "phase-plan", attempt_id: "attempt-1" });
  const cursor = result.next_cursor as string;
  expect(JSON.parse(Buffer.from(cursor, "base64url").toString())).toMatchObject({ phase: "phase-plan", attempt: "attempt-1", server: "server-next" });
  fetchMock.mockReset();
  await expect(executionSessionsCommand.handler({ positionals: ["execution"], values: { cursor, phase: "phase-build" } })).rejects.toThrow("other --phase/--attempt");
  expect(fetchMock).not.toHaveBeenCalled();
  fetchMock.mockResolvedValueOnce(response(status)).mockResolvedValueOnce(response(page("native-next", null)));
  await executionSessionsCommand.handler({ positionals: ["execution"], values: { cursor, json: true } });
  const continued = urls()[1]!;
  expect(continued.searchParams.get("phase_id")).toBe("phase-plan");
  expect(continued.searchParams.get("cursor")).toBe("server-next");
});

it("rejects blank filters before network access", async () => {
  await expect(executionSessionsCommand.handler({ positionals: ["execution"], values: { phase: " " } })).rejects.toThrow("Invalid --phase");
  expect(fetchMock).not.toHaveBeenCalled();
});

it("rejects a cursor from another installation before requesting a page", async () => {
  fetchMock.mockResolvedValueOnce(response(status));
  const cursor = Buffer.from(JSON.stringify({ source: "other", execution: "execution", snapshot: snapshot.snapshot_id, server: "server-cursor" })).toString("base64url");
  await expect(executionSessionsCommand.handler({ positionals: ["execution"], values: { cursor } })).rejects.toThrow("another run or installation");
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

it("shows pending without inventing an empty published inventory", async () => {
  fetchMock.mockResolvedValueOnce(response({ ...status, snapshot: null, reconstruction_status: "pending" }));
  await executionSessionsCommand.handler({ positionals: ["execution"], values: { json: true } });
  const result = JSON.parse(output());
  expect(result.status.snapshot).toBeNull();
  expect(result.revision).toBeNull();
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

for (const state of ["unknown", "open", "missing", "unsupported", "conflicting"]) {
  it(`require-complete fails on ${state} coverage after printing valid data`, async () => {
    const partial = { ...status, snapshot: { ...snapshot, coverage: { state } }, summary: { ...summary, coverage_state: state, complete: false } };
    fetchMock.mockResolvedValueOnce(response(partial)).mockResolvedValueOnce(response(page("native", null)));
    await expect(executionSessionsCommand.handler({ positionals: ["execution"], values: { json: true, "require-complete": true } })).rejects.toThrow(`coverage ${state}`);
    expect(JSON.parse(output()).pages).toHaveLength(1);
  });
}

const reconciled = { ...status, snapshot: { ...snapshot, coverage: { state: "reconciled" } }, summary: { ...summary, coverage_state: "reconciled", complete: true } };

/** Every section of the reconciled revision, two node pages, one page elsewhere. */
function serveReconciled(body: object = reconciled) {
  fetchMock.mockImplementation(async (request: Request) => {
    const url = new URL(request.url);
    if (url.pathname.endsWith("/session-inventory")) return response(body);
    const kind = url.pathname.split("/").pop()!;
    if (kind === "node" && !url.searchParams.get("cursor")) return response({ ...page("native-a", "n2"), snapshot: reconciled.snapshot });
    return response({ ...page("native-b", null, kind), snapshot: reconciled.snapshot });
  });
}

it("require-complete passes only for reconciled coverage AND a full traversal of the head", async () => {
  serveReconciled();
  await executionSessionsCommand.handler({ positionals: ["execution"], values: { all: true, json: true, "require-complete": true } });
  const result = JSON.parse(output());
  expect(result).toMatchObject({ complete: true, coverage_complete: true, traversal_complete: true, pending_sections: [], page_budget_exhausted: false });
  // Reconciled but newer evidence pending: the server says incomplete, and the CLI obeys.
  serveReconciled({ ...reconciled, reconstruction_status: "pending", summary: { ...reconciled.summary, complete: false } });
  await expect(executionSessionsCommand.handler({ positionals: ["execution"], values: { all: true, "require-complete": true } })).rejects.toThrow("not complete");
});

it("reconciled coverage with a one-page budget never claims complete", async () => {
  serveReconciled();
  await expect(executionSessionsCommand.handler({ positionals: ["execution"], values: { all: true, json: true, "max-pages": "1", "require-complete": true } }))
    .rejects.toThrow(/reconciled but this read is partial \(pending: node, membership/);
  const result = JSON.parse(output());
  expect(result.complete).toBe(false);
  expect(result.coverage_complete).toBe(true);
  expect(result.traversal_complete).toBe(false);
  expect(result.page_budget_exhausted).toBe(true);
  expect(result.pending_sections).toEqual(["node", "membership", "edge", "capture", "gap", "binding", "retraction"]);
  expect(result.gaps).toBeNull();
  expect(JSON.parse(Buffer.from(result.next_cursor, "base64url").toString())).toMatchObject({ kind: "node", server: "n2" });
  expect(fetchMock).toHaveBeenCalledTimes(2);
});

it("reconciled coverage read by one section, one page or one phase is partial", async () => {
  for (const values of [{}, { all: true, kind: "node" }, { all: true, phase: "phase-plan" }]) {
    serveReconciled();
    vi.mocked(process.stdout.write).mockClear();
    await executionSessionsCommand.handler({ positionals: ["execution"], values: { ...values, json: true } });
    const result = JSON.parse(output());
    expect(result.coverage_complete).toBe(true);
    expect(result.complete).toBe(false);
  }
  serveReconciled();
  vi.mocked(process.stdout.write).mockClear();
  await executionSessionsCommand.handler({ positionals: ["execution"], values: { all: true, "max-pages": "1" } });
  expect(output()).toContain("Partial listing: not read to the end: node, membership");
  expect(output()).toContain("Stopped at the --max-pages budget.");
});

it("rejects an out-of-range page budget before network access", async () => {
  await expect(executionSessionsCommand.handler({ positionals: ["execution"], values: { "max-pages": "0" } })).rejects.toThrow("max-pages");
  expect(fetchMock).not.toHaveBeenCalled();
});

it("surfaces an expired cursor with its restart hint", async () => {
  const cursor = Buffer.from(JSON.stringify({ source: "installation", execution: "execution", snapshot: snapshot.snapshot_id, server: "old" })).toString("base64url");
  fetchMock.mockResolvedValueOnce(response(status)).mockResolvedValueOnce(response({
    detail: { code: "cursor_expired", message: "Pinned inventory revision is no longer available; restart from the head", restart: true, mismatched: [] },
  }, 410));
  await expect(executionSessionsCommand.handler({ positionals: ["execution"], values: { cursor } })).rejects.toThrow(/cursor_expired.*rerun without --cursor/);
});

// Completeness is the server's verdict (summary.complete), derived from the
// sealed coverage contract and the head being current; the CLI adds only its
// own traversal completeness (#1398 D).
const withCoverage = (state: string, reconstruction = "current") => {
  const sealed = { ...snapshot, coverage: { state, contract_id: "syntropic-invocations/1", expected_count: 1, missing_keys: [] } };
  return {
    status: {
      ...status, snapshot: sealed, reconstruction_status: reconstruction,
      summary: { ...summary, coverage_state: state, complete: state === "reconciled" && reconstruction === "current" },
    },
    page: { ...page("native", null), snapshot: sealed },
  };
};

it("require-complete passes once the host seal reconciles coverage and every section is read", async () => {
  const sealed = withCoverage("reconciled");
  serveReconciled(sealed.status);
  await executionSessionsCommand.handler({ positionals: ["execution"], values: { all: true, json: true, "require-complete": true } });
  expect(JSON.parse(output())).toMatchObject({ complete: true, coverage_complete: true });
  // The same sealed head read one page at a time is a partial view.
  fetchMock.mockReset();
  fetchMock.mockResolvedValueOnce(response(sealed.status)).mockResolvedValueOnce(response(sealed.page));
  await expect(executionSessionsCommand.handler({ positionals: ["execution"], values: { json: true, "require-complete": true } })).rejects.toThrow("read is partial");
});

it.each(["open", "missing", "unsupported", "conflicting"])("require-complete rejects %s coverage", async (state) => {
  const unsealed = withCoverage(state);
  fetchMock.mockResolvedValueOnce(response(unsealed.status)).mockResolvedValueOnce(response(unsealed.page));
  await expect(executionSessionsCommand.handler({ positionals: ["execution"], values: { json: true, "require-complete": true } })).rejects.toThrow(`not complete (coverage ${state}`);
});

it("require-complete rejects a reconciled revision that is no longer current", async () => {
  const stale = withCoverage("reconciled", "pending");
  fetchMock.mockResolvedValueOnce(response(stale.status)).mockResolvedValueOnce(response(stale.page));
  await expect(executionSessionsCommand.handler({ positionals: ["execution"], values: { json: true, "require-complete": true } })).rejects.toThrow("not complete (coverage reconciled, reconstruction pending)");
});

it("rejects nonadvancing pagination instead of looping", async () => {
  fetchMock.mockResolvedValueOnce(response(status))
    .mockResolvedValueOnce(response(page("native", "same")))
    .mockResolvedValueOnce(response(page("native", "same")));
  await expect(executionSessionsCommand.handler({ positionals: ["execution"], values: { all: true, kind: "node" } })).rejects.toThrow("did not advance");
  expect(fetchMock).toHaveBeenCalledTimes(3);
});

it("refresh schedules management work with the caller key and reports its durable job", async () => {
  const job = { job_id: snapshot.snapshot_id, run, stage: "pending", evidence_watermark: 3 };
  fetchMock.mockResolvedValueOnce(response({ job_id: job.job_id }))
    .mockResolvedValueOnce(response(job))
    .mockResolvedValueOnce(response({ ...status, snapshot: null, reconstruction_status: "pending" }));
  await executionSessionsCommand.handler({ positionals: ["execution"], values: { refresh: true, "idempotency-key": "retry", json: true } });
  const request = fetchMock.mock.calls[0]![0] as Request;
  expect(request.method).toBe("POST");
  expect(await request.json()).toEqual({ idempotency_key: "retry", include_history: false });
  expect(JSON.parse(output()).refresh.job_id).toBe(job.job_id);
  expect(fetchMock).toHaveBeenCalledTimes(3);
});

it("preserves capture restrictions and binds continuation cursors to the section", async () => {
  const capturePage = { snapshot, kind: "capture", filters: {}, items: [], item_keys: [], next_cursor: "server-capture",
    body_overrides: [{ archive_sha256: "a".repeat(64), status: "expired" }] };
  fetchMock.mockResolvedValueOnce(response(status)).mockResolvedValueOnce(response(capturePage));
  await executionSessionsCommand.handler({ positionals: ["execution"], values: { kind: "capture", json: true } });
  const result = JSON.parse(output());
  expect(result.pages[0].body_overrides).toEqual(capturePage.body_overrides);
  const cursor = result.next_cursor;
  expect(JSON.parse(Buffer.from(cursor, "base64url").toString()).kind).toBe("capture");
  fetchMock.mockReset();
  await expect(executionSessionsCommand.handler({ positionals: ["execution"], values: { cursor, kind: "node" } })).rejects.toThrow("another section");
  expect(fetchMock).not.toHaveBeenCalled();
  vi.mocked(process.stdout.write).mockClear();
  fetchMock.mockResolvedValueOnce(response(status)).mockResolvedValueOnce(response({ ...capturePage, next_cursor: null }));
  await executionSessionsCommand.handler({ positionals: ["execution"], values: { cursor, json: true } });
  const continued = urls()[1]!;
  expect(continued.pathname).toMatch(/\/capture$/);
  expect(continued.searchParams.get("cursor")).toBe("server-capture");
});

it("prints historical capture availability separately from current expiry", async () => {
  const hash = "a".repeat(64);
  fetchMock.mockResolvedValueOnce(response(status)).mockResolvedValueOnce(response({
    snapshot, kind: "capture", filters: {}, item_keys: [], next_cursor: null,
    items: [{ node: { kind: "transcript", source_instance_id: "installation", harness: "codex", local_id: "native" }, destination: "local", availability: "present", archived_byte_hash: hash }],
    body_overrides: [{ archive_sha256: hash, status: "expired" }],
  }));
  await executionSessionsCommand.handler({ positionals: ["execution"], values: { kind: "capture" } });
  expect(output()).toContain("transcript:codex/native\tlocal: recorded=present; current=expired");
  expect(output()).toContain(hash);
});

it("human --all output groups by phase/attempt with full IDs, parent, local and replication state", async () => {
  const leader = { kind: "transcript", source_instance_id: "installation", harness: "claude", local_id: "claude-leader-full-id" };
  const child = { kind: "transcript", source_instance_id: "installation", harness: "claude", local_id: "claude-child-full-id" };
  const platform = { kind: "platform", source_instance_id: "installation", local_id: "sess-platform-full-id" };
  const [L, C, P] = ["l", "c", "p"].map(c => c.repeat(64));
  const pages: Record<string, unknown> = {
    node: { items: [{ ref: leader }, { ref: child }, { ref: platform }], item_keys: [{ node_key: L }, { node_key: C }, { node_key: P }] },
    membership: { items: [{ node: leader, run, phase_id: "phase-plan", attempt_id: "attempt-1", confidence: "registered", evidence: [] },
      { node: platform, run, phase_id: "phase-plan", attempt_id: "attempt-1", confidence: "registered", evidence: [] }], item_keys: [{ node_key: L }, { node_key: P }] },
    edge: { items: [{ parent: leader, child, relation: "spawn", confidence: "corroborated", evidence: [] }], item_keys: [{ node_key: L, peer_key: C }] },
    capture: { items: [{ node: leader, availability: "present", destination: "local", archived_byte_hash: "a".repeat(64), receipt_sequence: 1 }], item_keys: [{ node_key: L }],
      body_overrides: [] },
    gap: { items: [{ reason: "unlinked_native_transcript", node_keys: [C] }], item_keys: [{}] },
    binding: { items: [{ owner: platform, transcript: leader, confidence: "registered", evidence: [] }], item_keys: [{ node_key: P, peer_key: L }] },
    retraction: { items: [], item_keys: [] },
  };
  fetchMock.mockImplementation(async (request: Request) => {
    const url = new URL(request.url);
    if (url.pathname.endsWith("/session-inventory")) return response({ ...status, summary: { ...summary, remote_replication: "disabled" } });
    const kind = url.pathname.split("/").pop()!;
    return response({ snapshot, kind, filters: {}, next_cursor: null, body_overrides: [], ...(pages[kind] as object) });
  });
  await executionSessionsCommand.handler({ positionals: ["execution"], values: { all: true } });
  const text = output();
  expect(text).toContain("Coverage: unknown: no completeness contract for this run");
  expect(text).toContain(summary.counts_display);
  expect(text).toContain("Phase phase-plan / attempt attempt-1");
  expect(text).toContain("transcript:claude/claude-leader-full-id");
  expect(text).toContain("platform/sess-platform-full-id");
  expect(text).toContain("represents: platform/sess-platform-full-id");
  expect(text).toContain("local: present; replication: remote replication disabled");
  expect(text).toMatch(/Unlinked \(no phase membership\)\n {2}transcript:claude\/claude-child-full-id\n.*\n {4}parent: transcript:claude\/claude-leader-full-id \(spawn, corroborated\)/);
  expect(text).toContain("unlinked_native_transcript: transcript:claude/claude-child-full-id");
});

it("rejects unsupported sections before network access", async () => {
  await expect(executionSessionsCommand.handler({ positionals: ["execution"], values: { kind: "invalid" } })).rejects.toThrow("Invalid inventory kind");
  expect(fetchMock).not.toHaveBeenCalled();
});

it("rejects a response with a mismatched section", async () => {
  fetchMock.mockResolvedValueOnce(response(status)).mockResolvedValueOnce(response(page("native", null)));
  await expect(executionSessionsCommand.handler({ positionals: ["execution"], values: { kind: "edge" } })).rejects.toThrow("another section");
});

it("rejects legacy integer-offset cursors; the server cursor is required", async () => {
  const legacy = Buffer.from(JSON.stringify({ source: "installation", execution: "execution", snapshot: snapshot.snapshot_id, after: 0 })).toString("base64url");
  await expect(executionSessionsCommand.handler({ positionals: ["execution"], values: { cursor: legacy } })).rejects.toThrow("Invalid inventory cursor");
  expect(fetchMock).not.toHaveBeenCalled();
});

it("continues node cursors without requiring a section field", async () => {
  const cursor = Buffer.from(JSON.stringify({ source: "installation", execution: "execution", snapshot: snapshot.snapshot_id, server: "server-node" })).toString("base64url");
  fetchMock.mockResolvedValueOnce(response(status)).mockResolvedValueOnce(response(page("legacy-next", null)));
  await executionSessionsCommand.handler({ positionals: ["execution"], values: { cursor, json: true } });
  expect(JSON.parse(output()).pages[0].items[0].ref.local_id).toBe("legacy-next");
  const url = urls()[1]!;
  expect(url.pathname).toMatch(/\/node$/);
  expect(url.searchParams.get("cursor")).toBe("server-node");
});
