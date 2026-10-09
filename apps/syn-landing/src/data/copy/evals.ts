/** "04 Compounding improvement" (#evals), from the v4 boards. Links are spelled out: importing DOCS_URL from ../copy would be a cycle (copy.ts re-exports this file). */
export const EVALS_COPY = {
  num: "04",
  eyebrow: "Compounding improvement",
  title: "Every run makes the next one better.",
  lede:
    "Your run history becomes evals: real bugs replayed against every model and workflow, scored out of 100 by a judge, next to what each run cost. Change a prompt or a model, and see whether it actually helped. Try it: pick a model on the right.",
  guide: { label: "Read the evals guide", href: "https://docs.syntropic137.com/docs/guide/evals" },
  windowUrl: "localhost:8137/evals/shared-esp-stream",
  loopLabel: "How evals work",
  loop: [
    { title: "Capture", body: 'A real bug from your history becomes a case: the baseline commit, the task, and what "caught it" means.' },
    { title: "Replay", body: "Every model or workflow you want to compare runs the case in its own clean workspace." },
    { title: "Judge", body: "A judge model scores each run out of 100 and writes down its evidence." },
    { title: "Decide", body: "Rank by quality per dollar, catch regressions the day they happen, and keep the winner." },
  ],
} as const;
