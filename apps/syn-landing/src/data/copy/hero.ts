/** Hero copy ("Agent work that compounds."), from the v4 Landing and PhoneLanding boards. */

export const INSTALL_COMMAND = "npx @syntropic137/setup init";

export const HERO = {
  badge: { tag: "New", text: "Evals: measure which model and prompt actually work", href: "#evals" },
  title: "Agent work that compounds.",
  lede: "Turn one-off agent sessions into repeatable workflows. Run them on Claude Code or Codex, see every step, and make every run better than the last.",
  installNote: "Open source, MIT. Node 18+ and Docker. Your dashboard is live at localhost:8137 in about five minutes.",
  copyLabel: "Copy",
  copiedLabel: "Copied",
  copyFailedLabel: "Copy failed",
  copiedAnnounce: "Install command copied to the clipboard",
  copyFailedAnnounce: "Could not copy. Select the command and copy it.",
  copyAria: "Copy install command",
  cityLabel: "A city of blocks, one per day of agent runs, with the Syntropic137 S rising from the middle",
  markLabel: "The Syntropic137 S, built from cubes",
} as const;
