/**
 * SAMPLE DATA: recorded cost, tokens, score and tool calls of one run of
 * implement-and-review (v4 boards: "What is Syntropic137?" card 3 and
 * "03 Fully observable"). Token splits follow the board's band: 52 / 18 /
 * 21 / 9 percent cache read, cache write, output, input.
 */
import type { ToolLogRow } from "@syn137/skyline-core/patterns";

const split = (total: number) => ({
  cacheRead: Math.round(total * 0.52),
  cacheWrite: Math.round(total * 0.18),
  output: Math.round(total * 0.21),
  input: Math.round(total * 0.09),
});

/** "What is" card 3: the run's recorded cost and review score. */
export const RECORDED_RUN = {
  host: "localhost:8137",
  cost: "$0.31",
  detail: "842k tokens · 214 tool calls",
  tokens: split(842_000),
  score: 88,
  scoreMax: 100,
  verdict: "Faster and cheaper than last week's runs",
};

/** "03 Fully observable": the live run. */
export const LIVE_RUN = {
  meta: "live · implement-and-review · run #142",
  cost: "$0.2162",
  detail: "1.12M tokens · 214 tool calls · 6m 12s",
  tokens: split(1_120_000),
};

export const TOOL_ROWS: readonly ToolLogRow[] = [
  { time: "14:02:11", tool: "Read", target: "src/domain/aggregate.py", duration: "42ms" },
  { time: "14:02:14", tool: "Grep", target: '"apply_event" -n', duration: "118ms" },
  { time: "14:02:19", tool: "Bash", target: "pytest -q tests/domain", duration: "8.4s" },
  { time: "14:02:31", tool: "Write", target: "docs/event-sourcing.md", duration: "12ms" },
  { time: "14:02:33", tool: "Read", target: "src/projections/list.py", duration: "31ms" },
  { time: "14:02:40", tool: "Edit", target: "projection.py +12 −3", duration: "9ms" },
  { time: "14:02:52", tool: "Bash", target: "ruff check .", duration: "1.2s" },
  { time: "14:03:01", tool: "Read", target: "tests/test_replay.py", duration: "28ms" },
];
