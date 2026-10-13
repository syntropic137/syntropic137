/** "Why a platform": the comparison table, from the v4 boards. */
export const WHY_PLATFORM_COPY = {
  eyebrow: "Why a platform",
  title: "Running agents is easy. Trusting them is not.",
  lede: "Syntropic137 is the difference between a demo and a team of agents you can depend on.",
  caption: "Running agents by hand compared with running them on Syntropic137",
  columns: { question: "Question", without: "By hand", with: "With Syntropic137" },
  rows: [
    { question: "What the agent did", without: "Scroll back through a terminal", with: "Every tool call, kept forever" },
    { question: "What it cost", without: "Check the invoice next month", with: "Per run, per phase, per token type" },
    { question: "Is it getting better", without: "Gut feel", with: "Judge scores and trends over time" },
    { question: "Where it ran", without: "Your laptop, with your keys", with: "A throwaway container" },
    { question: "Who starts it", without: "You, every time", with: "GitHub events, on a budget" },
  ],
} as const;
