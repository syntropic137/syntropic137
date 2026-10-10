/** "02 Multi-harness" copy (#harnesses), from the v4 boards. */

export const ANY_HARNESS = {
  num: "02",
  eyebrow: "Multi-harness",
  title: "Claude Code or Codex. Per phase.",
  lede: "Pick the best agent for each step instead of one vendor for everything. Build with one, review with the other, and delegate subtasks between them.",
  points: [
    { title: "Mix vendors in one workflow", body: "Each phase names its provider and model." },
    { title: "A second opinion built in", body: "Cross-vendor review catches what one model misses." },
    { title: "One record for both", body: "The same telemetry, costs and evals, whichever harness ran." },
  ],
  lanesLabel: "One workflow, four phases: Claude Code plans and fixes, Codex implements and reviews",
} as const;
