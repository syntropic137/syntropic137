import { createHash } from "node:crypto";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { executionTranscriptCommand } from "../../src/commands/execution-transcript.js";

const fetchMock = vi.fn();
const body = Buffer.from([123, 125, 13, 10, 0, 255]);
const revision = createHash("sha256").update(body).digest("hex");
const result = { status: "present", archive_sha256: revision, size: body.length, content_format: "native", content_base64: body.toString("base64") };
const response = (value: unknown) => new Response(JSON.stringify(value), { headers: { "Content-Type": "application/json" } });
const positionals = ["execution", "codex", "opaque/雪", revision];
beforeEach(() => { fetchMock.mockReset(); vi.stubGlobal("fetch", fetchMock); vi.spyOn(process.stdout, "write").mockReturnValue(true); });
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("writes verified native bytes without a newline or JSON conversion", async () => {
  fetchMock.mockResolvedValue(response(result));
  await executionTranscriptCommand.handler({ positionals, values: { raw: true } });
  expect(process.stdout.write).toHaveBeenCalledWith(body);
  const url = new URL((fetchMock.mock.calls[0]![0] as Request).url);
  expect(url.searchParams.get("native_id")).toBe("opaque/雪");
  expect(url.searchParams.get("harness")).toBe("codex");
});

it.each([
  { ...result, archive_sha256: "a".repeat(64) },
  { ...result, size: 99 },
  { ...result, content_base64: "!" + result.content_base64 },
  { ...result, content_base64: Buffer.from("changed").toString("base64") },
])("rejects corrupted responses before emitting bytes", async value => {
  fetchMock.mockResolvedValue(response(value));
  await expect(executionTranscriptCommand.handler({ positionals, values: { raw: true } })).rejects.toThrow();
  expect(process.stdout.write).not.toHaveBeenCalled();
});

it.each(["missing", "not_captured", "too_large"])("reports %s without inventing a body", async status => {
  fetchMock.mockResolvedValue(response({ ...result, status, content_base64: null }));
  await expect(executionTranscriptCommand.handler({ positionals, values: { raw: true } })).rejects.toThrow(`Transcript unavailable: ${status}`);
  expect(process.stdout.write).not.toHaveBeenCalled();
});

it("rejects conflicting output flags before network access", async () => {
  await expect(executionTranscriptCommand.handler({ positionals, values: { raw: true, json: true } })).rejects.toThrow("cannot be combined");
  expect(fetchMock).not.toHaveBeenCalled();
});
