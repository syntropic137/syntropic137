/** Closing call to action (#start), from the v4 boards. */
export const INSTALL_COMMAND = "npx @syntropic137/setup init";

export const START_COPY = {
  title: "Make your agent work compound.",
  lede: "Repeatable workflows, any harness, every step on the record, better every run. Self-hosted and MIT licensed.",
  note: "Open source, MIT. Node 18+ and Docker. Your dashboard is live at localhost:8137 in about five minutes.",
  stepsLabel: "Three steps",
  steps: [
    { label: "Install", code: INSTALL_COMMAND },
    { label: "Run", code: 'syn workflow run research-package-v1 --task "…"' },
    { label: "Watch", code: "open http://localhost:8137" },
  ],
  wordmark: "SYNTROPIC137",
} as const;
