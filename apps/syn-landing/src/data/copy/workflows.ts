/** "01 Repeatable workflows" copy (#workflows), from the v4 boards. */

export const WORKFLOWS = {
  num: "01",
  eyebrow: "Repeatable workflows",
  title: "Write it once. Run it forever.",
  lede: "Turn the prompt you keep retyping into a workflow: phases in YAML, prompts in Markdown. Run it by hand, from the API, or let GitHub events start it.",
  points: [
    { title: "Phases with inputs and outputs", body: "Each phase hands its artifacts to the next, with timeouts and budgets." },
    { title: "Start it from anywhere", body: "The CLI, the API, or a GitHub event through a trigger." },
    { title: "Share and reuse", body: "Install workflows from any repo and pin the version." },
  ],
  /**
   * Ways to start a workflow. Commands are real: `syn workflow run`,
   * `syn workflow install --ref` (docs guide/workflows), and the trigger
   * event and preset from apps/syn-docs/content/docs/guide/triggers.mdx.
   */
  startFrom: [
    { label: "From the CLI", code: "syn workflow run implement-and-review" },
    { label: "From a GitHub event", code: "--event check_run.completed" },
    { label: "From a preset", code: "syn triggers enable self-healing" },
    { label: "From another repo", code: "syn workflow install owner/repo --ref main" },
  ],
} as const;
