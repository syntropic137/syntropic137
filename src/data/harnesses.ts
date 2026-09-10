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

export interface Harness {
  /** Value used by `agent.provider` in workflow YAML. */
  id: "claude" | "codex";
  /** Display name in prose and UI. */
  name: string;
  /** Vendor, for the "works with" strip. */
  vendor: string;
  /** True when the harness can also drive the platform, not just execute phases. */
  controlPlane: boolean;
  /**
   * Modifier class for the name's gradient, defined in globals.css.
   * Each harness wears its own vendor colour so the two read as distinct
   * products rather than one branded pair.
   */
  accentClass: string;
}

export const HARNESSES: readonly Harness[] = [
  {
    id: "claude",
    name: "Claude Code",
    vendor: "Anthropic",
    controlPlane: true,
    accentClass: "harness--claude",
  },
  {
    id: "codex",
    name: "Codex",
    vendor: "OpenAI",
    controlPlane: false,
    accentClass: "harness--codex",
  },
] as const;

/** "Claude Code and Codex", for inline prose. */
export const harnessList = (): string => {
  const names = HARNESSES.map((h) => h.name);
  if (names.length <= 1) return names[0] ?? "";
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
};
