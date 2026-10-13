/**
 * SAMPLE DATA: plan-implement-review, one workflow across two harnesses
 * (v4 boards, "02 Any harness"). Providers are `agent.provider` values
 * from src/data/harnesses.ts.
 */
import type { HarnessPhase } from "@syn137/skyline-core/patterns";

export const LANES_TITLE = "plan-implement-review · one workflow, two vendors";

export const LANE_PHASES: readonly HarnessPhase[] = [
  { name: "plan", provider: "claude", span: 2 },
  { name: "implement", provider: "codex", span: 3 },
  { name: "fix", provider: "claude", span: 2 },
  { name: "review", provider: "codex", span: 2 },
];

export const LANE_FACTS: readonly { label: string; value: string }[] = [
  { label: "Phases", value: "4, across 2 harnesses" },
  { label: "Second opinion", value: "Codex reviews Claude" },
  { label: "Telemetry", value: "Identical for both" },
];
