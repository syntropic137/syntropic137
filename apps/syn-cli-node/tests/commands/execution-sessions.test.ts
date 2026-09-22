import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { executionSessionsCommand } from "../../src/commands/execution-sessions.js";

const fetchMock = vi.fn();
const run = { source_instance_id: "installation", execution_id: "execution" };
const snapshot = {
  snapshot_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", run, revision: "revision",
  resolver_version: "test/1", evidence_watermark: 3,
  coverage: { state: "unknown" }, counts: { node: 2, gap: 1 },
};
const status = { run, snapshot, reconstruction_status: "current", later_evidence_pending: false };
const page = (id: string, next: number | null) => ({
  snapshot, kind: "node", items: [{ ref: { kind: "transcript", local_id: id, harness: "fake", source_instance_id: "installation" } }], next_after: next,
});
const response = (body: unknown) => new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } });
const output = () => vi.mocked(process.stdout.write).mock.calls.map(c => String(c[0])).join("");

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  vi.spyOn(process.stdout, "write").mockReturnValue(true);
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("streams all pages from the original revision with full native IDs", async () => {
  fetchMock.mockResolvedValueOnce(response(status))
    .mockResolvedValueOnce(response(page("native-one-full-id", 0)))
    .mockResolvedValueOnce(response(page("native-two-full-id", null)));
  await executionSessionsCommand.handler({ positionals: ["execution"], values: { all: true, json: true, limit: "1" } });
  const result = JSON.parse(output());
  expect(result.pages).toHaveLength(2);
  expect(result.pages[1].items[0].ref.local_id).toBe("native-two-full-id");
  expect(result.next_cursor).toBeNull();
  const urls = fetchMock.mock.calls.map(c => new URL((c[0] as Request).url));
  expect(urls[1]!.pathname).toContain(snapshot.snapshot_id);
  expect(urls[2]!.pathname).toContain(snapshot.snapshot_id);
  expect(urls[2]!.searchParams.get("after")).toBe("0");
});

it("rejects a cursor from another installation before requesting a page", async () => {
  fetchMock.mockResolvedValueOnce(response(status));
  const cursor = Buffer.from(JSON.stringify({ source: "other", execution: "execution", snapshot: snapshot.snapshot_id, after: 0 })).toString("base64url");
  await expect(executionSessionsCommand.handler({ positionals: ["execution"], values: { cursor } })).rejects.toThrow("another run or installation");
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

it("shows pending without inventing an empty published inventory", async () => {
  fetchMock.mockResolvedValueOnce(response({ ...status, snapshot: null, reconstruction_status: "pending" }));
  await executionSessionsCommand.handler({ positionals: ["execution"], values: { json: true } });
  expect(JSON.parse(output()).status.snapshot).toBeNull();
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

it("require-complete rejects unknown coverage after printing valid data", async () => {
  fetchMock.mockResolvedValueOnce(response(status)).mockResolvedValueOnce(response(page("native", null)));
  await expect(executionSessionsCommand.handler({ positionals: ["execution"], values: { json: true, "require-complete": true } })).rejects.toThrow("not reconciled");
  expect(JSON.parse(output()).pages).toHaveLength(1);
});

it("rejects nonadvancing pagination instead of looping", async () => {
  fetchMock.mockResolvedValueOnce(response(status))
    .mockResolvedValueOnce(response(page("native", 0)))
    .mockResolvedValueOnce(response(page("native", 0)));
  await expect(executionSessionsCommand.handler({ positionals: ["execution"], values: { all: true } })).rejects.toThrow("did not advance");
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
  expect(await request.json()).toEqual({ idempotency_key: "retry" });
  expect(JSON.parse(output()).refresh.job_id).toBe(job.job_id);
  expect(fetchMock).toHaveBeenCalledTimes(3);
});
