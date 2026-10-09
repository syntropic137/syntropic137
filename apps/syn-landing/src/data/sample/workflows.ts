/**
 * SAMPLE DATA: the example workflow file and trigger shown in "What is
 * Syntropic137?" and "01 Repeatable workflows" (v4 boards). The keys are
 * real (workflows/examples/*.yaml): `phases[].agent.provider` / `model`,
 * and `prompt_file` for a prompt kept in a Markdown file (the board wrote
 * `prompt_template`, which holds an inline prompt, not a path).
 */

/** One YAML line: indent, optional list dash, key, and value (a provider value takes its harness colour). */
export interface YamlLine {
  indent: number;
  dash?: boolean;
  key: string;
  value?: string;
  /** `{ provider: x, model: y }` written inline, as on the board. */
  agent?: { provider: "claude" | "codex"; model: string };
}

export const WORKFLOW_FILE = "workflows/implement-and-review.yaml";
export const WORKFLOW_ID = "implement-and-review";

export const WORKFLOW_YAML: readonly YamlLine[] = [
  { indent: 0, key: "id", value: WORKFLOW_ID },
  { indent: 0, key: "inputs" },
  { indent: 1, dash: true, key: "name", value: "task" },
  { indent: 0, key: "phases" },
  { indent: 1, dash: true, key: "id", value: "implement" },
  { indent: 2, key: "agent", agent: { provider: "claude", model: "sonnet" } },
  { indent: 2, key: "prompt_file", value: "prompts/implement.md" },
  { indent: 1, dash: true, key: "id", value: "review" },
  { indent: 2, key: "agent", agent: { provider: "codex", model: "gpt-5.6-sol" } },
  { indent: 2, key: "prompt_file", value: "prompts/review.md" },
];

/** The trigger card: a rule read as a sentence (guards from guide/triggers.mdx: daily limit, budget). */
export const TRIGGER = {
  meta: "trigger · self-heal-ci · active",
  rule: [
    { word: "When", text: " CI fails on a pull request, " },
    { word: "run", text: " " },
    { workflow: WORKFLOW_ID, text: ", " },
    { word: "at most", text: " 3 times a day, " },
    { word: "under", text: " $2." },
  ],
} as const;

/** "Run it anywhere": the two phases of one run. */
export const RUN_PHASES = [
  { name: "implement", provider: "claude", model: "claude-sonnet-5-5", container: "container ws-1", status: "done · 3m 02s", progress: 100 },
  { name: "review", provider: "codex", model: "gpt-5.6-sol", container: "container ws-2", status: "running", progress: 60 },
] as const;
export const RUN_COMMAND = `syn workflow run ${WORKFLOW_ID}`;
