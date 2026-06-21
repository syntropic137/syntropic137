# Cross-harness observability research campaign

Owner: Mac-side /loop (cron c3a59b7c), orchestrating VPS research lanes.
Started: 2026-06-20. Budgets flush; spend liberally (Opus lanes + Codex cross-review).

## Mission / goal
Design + evidence-validate a STANDARDIZED way to get FULL observability on every
coding-agent harness (Claude, Codex, Gemini, PI) inside Syntropic137. Generalize
the mechanism that ALREADY works for Claude today (see Background), NOT Claude
Code native OTLP alone.

End state: a clean OTLP-shaped layer ON TOP of the workspace as the tidy
integration surface, with per-harness EXPORTER ADAPTERS underneath handling the
messy extraction (hooks / session logs / transcripts / stdout / capture-pane).

## Background (ground truth, confirm in L1)
Syntropic137 observability has TWO channels into syn-collector -> agent_events:
1. PLUGIN-HOOK / JSONL channel: the observability plugin's git hooks
   (post-commit, pre-push, etc.) emit agentic_events to collector /events. THIS
   is the channel that reliably delivers events/session data for Claude today.
2. Native OTLP channel (CLAUDE_CODE_ENABLE_TELEMETRY): cost/token metrics. Our
   2026-06-18 experiment (commit 2ca5751f) could NOT demonstrate this landing
   even from claude -p in the dev stack (COLLECTOR_URL empty + incomplete env).
The reusable, proven pattern is therefore the HOOK + SESSION-LOG + EXPORTER
approach, with OTLP as a presentation layer on top.

## Phases + lanes
Phase 1 (parallel, this campaign's first fan-out):
- L1 GROUND TRUTH: document EXACTLY how Claude obs works in syn137 today (the
  observability plugin, its hooks, agentic_events emission, /events JSONL schema,
  session-log ingestion, how rows land in agent_events). This is the template to
  generalize. Output: obs-L1-claude-groundtruth.md
- L2 CODEX SURFACE: what does Codex CLI expose? ~/.codex session/rollout/transcript
  files, any hooks, any telemetry/OTLP, usage/cost events, exit signals; how to
  extract cost/tokens/lifecycle for an exporter adapter. Output: obs-L2-codex-surface.md
- L3 GEMINI SURFACE: same for Gemini CLI; note CLI deprecation -> Antigravity and
  research the successor's surface too. Output: obs-L3-gemini-surface.md
- L4 PI SURFACE: identify what the "PI" coding-agent harness is, find its
  observability surface; if not identifiable from the box, FLAG operator-input
  needed. Output: obs-L4-pi-surface.md

Phase 2 (after L1-L4 land):
- L5 DESIGN SYNTHESIS: the standardized abstraction. Normalized event schema +
  per-harness exporter adapter pattern + the OTLP-shaped top layer + the minimal
  seam in agentic-primitives/syn137 + how interactive (capture-pane) vs -p differ.
  Output: obs-L5-design.md. THEN a Codex cross-model review (VERDICT-gated).

## Definition of Done
(a) per-harness surface map for codex/gemini/pi (L2-L4), AND
(b) evidence-backed L5 design doc cross-model reviewed.
NOT done at "idea". Surface operator-input items (esp. PI identity/access).

## Findings file paths (all in ~/swarm-tasks/)
obs-L1-claude-groundtruth.md, obs-L2-codex-surface.md, obs-L3-gemini-surface.md,
obs-L4-pi-surface.md, obs-L5-design.md
