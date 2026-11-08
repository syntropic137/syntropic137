/**
 * `syn execution watch <id>` is the noun-verb form of `syn watch execution <id>`
 * (#1633). Both must run the one implementation: same stream, same output.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../src/client/sse.js", () => ({ streamSSE: vi.fn() }));

import { streamSSE, type SSEEvent } from "../../src/client/sse.js";
import { executionGroup } from "../../src/commands/execution.js";
import { watchGroup } from "../../src/commands/watch.js";
import { CLI } from "../../src/framework/cli.js";

const EXECUTION_ID = "exec-1633-noun-verb";

async function* oneEvent(): AsyncGenerator<SSEEvent> {
  yield {
    event_type: "PhaseStarted",
    timestamp: "2026-11-08T12:00:00Z",
    data: { execution_id: EXECUTION_ID, phase_name: "implement" },
  } as SSEEvent;
}

function createCli(): CLI {
  return new CLI({ name: "syn", description: "Test CLI", version: "1.0.0" })
    .addGroup(executionGroup)
    .addGroup(watchGroup);
}

describe("syn execution watch", () => {
  let stdout: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    vi.spyOn(process, "exit").mockImplementation((() => {}) as unknown as (code?: number) => never);
    stdout = vi.spyOn(process.stdout, "write").mockReturnValue(true);
    vi.spyOn(process.stderr, "write").mockReturnValue(true);
    vi.mocked(streamSSE).mockImplementation(() => oneEvent());
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.mocked(streamSSE).mockReset();
  });

  async function run(argv: string[]): Promise<{ streamed: unknown[][]; output: string }> {
    vi.mocked(streamSSE).mockClear();
    stdout.mockClear();
    await createCli().run(argv);
    return {
      streamed: vi.mocked(streamSSE).mock.calls,
      output: stdout.mock.calls.map((c) => String(c[0])).join(""),
    };
  }

  it("streams the same execution and prints the same output as `syn watch execution`", async () => {
    const legacy = await run(["watch", "execution", EXECUTION_ID]);
    const nounVerb = await run(["execution", "watch", EXECUTION_ID]);

    expect(legacy.streamed).toEqual([[`/sse/executions/${EXECUTION_ID}`]]);
    expect(nounVerb.streamed).toEqual(legacy.streamed);
    expect(nounVerb.output).toContain(`Watching execution ${EXECUTION_ID}`);
    expect(nounVerb.output).toBe(legacy.output);
  });

  it("is the watch-execution handler, not a copy of it", () => {
    const nounVerb = executionGroup.getCommand("watch");
    const legacy = watchGroup.getCommand("execution");
    expect(nounVerb?.handler).toBe(legacy?.handler);
    expect(nounVerb?.args).toBe(legacy?.args);
    expect(nounVerb?.options).toBe(legacy?.options);
  });

  it("is listed by `syn execution --help`", async () => {
    const { output } = await run(["execution", "--help"]);
    expect(output).toMatch(/^\s+watch\b.*Stream live events for a specific execution/m);
  });
});
