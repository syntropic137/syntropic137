/** "What people build with it", from the v4 boards. */
export const USE_CASES_COPY = {
  eyebrow: "What people build with it",
  title: "Write it once. Let it run.",
  lede: "A few of the workflows people run on Syntropic137. Each ships as a starting point you can install and change.",
  cards: [
    { title: "Self-healing CI", body: "A check fails, an agent fixes it and pushes the fix to the PR.", trigger: "GitHub: check_run failed" },
    { title: "Second-opinion review", body: "Claude implements, Codex reviews, every PR, on a budget.", trigger: "GitHub: PR opened" },
    { title: "Research and docs", body: "Investigate a codebase or topic and write it up with sources.", trigger: "CLI or Claude Code" },
    { title: "Migrations and refactors", body: "Split a large change into planned, reviewed phases.", trigger: "CLI, one repo or many" },
    { title: "Issue to pull request", body: "Label an issue and get a tested PR back.", trigger: "GitHub issue event" },
    { title: "Nightly maintenance", body: "Dependency bumps, flaky-test hunts, changelog upkeep.", trigger: "CLI on a schedule" },
  ],
} as const;
