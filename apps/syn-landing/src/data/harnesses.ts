/**
 * Supported agent harnesses.
 *
 * A harness is the coding-agent CLI that executes a workflow phase inside a
 * Syntropic137 workspace. Phases select one per phase via `agent.provider` in
 * the workflow YAML, so a single workflow can mix harnesses and hand work
 * between them.
 *
 * Adding a harness should be an edit to this file, not a copy hunt through
 * components. Hero and AgentControlPlane render their harness lists from
 * HARNESSES, so a new entry appears in both without touching either. Prose that
 * says something specific about ONE harness stays hand-written, because that
 * claim does not generalise.
 *
 * Keep `controlPlane` honest: it is the difference between a claim we can back
 * and one we cannot.
 */

import type { CSSProperties } from "react";

export type HarnessId = "claude" | "codex";

export interface Harness {
  /** Value used by `agent.provider` in workflow YAML. */
  id: HarnessId;
  /** Display name in prose and UI. */
  name: string;
  /** Vendor, for the "works with" strip. */
  vendor: string;
  /** True when the harness can also drive the platform, not just execute phases. */
  controlPlane: boolean;
  /**
   * The harness colour: Skyline's `--sky-harness-<id>` token
   * (@syn137/skyline-themes), the same colour the dashboard and the
   * `<sky-harness-chip>` element use. Each harness wears its own vendor
   * colour so the two read as distinct products rather than one branded pair.
   */
  color: `var(--sky-harness-${HarnessId})`;
  /** Gradient for the name set as text (`background-clip: text`), `--sky-harness-<id>-gradient`. */
  gradient: `var(--sky-harness-${HarnessId}-gradient)`;
}

export const HARNESSES: readonly Harness[] = [
  {
    id: "claude",
    name: "Claude Code",
    vendor: "Anthropic",
    controlPlane: true,
    color: "var(--sky-harness-claude)",
    gradient: "var(--sky-harness-claude-gradient)",
  },
  {
    id: "codex",
    name: "Codex",
    vendor: "OpenAI",
    controlPlane: false,
    color: "var(--sky-harness-codex)",
    gradient: "var(--sky-harness-codex-gradient)",
  },
] as const;

/**
 * Inline style for a `.harness` name: hands the harness colour and gradient
 * to globals.css as `--harness-color` and `--harness-gradient`, so a new
 * harness needs an entry here and nothing in CSS.
 */
export const harnessStyle = (h: Harness): CSSProperties =>
  ({ "--harness-color": h.color, "--harness-gradient": h.gradient }) as CSSProperties;

/** "Claude Code and Codex", for inline prose. */
export const harnessList = (): string => {
  const names = HARNESSES.map((h) => h.name);
  if (names.length <= 1) return names[0] ?? "";
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
};
