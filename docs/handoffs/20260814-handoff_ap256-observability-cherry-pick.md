# Handoff: rescue the observability keepers out of agentic-primitives PR #256

**Date:** 2026-08-14
**Repo:** https://github.com/AgentParadise/agentic-primitives (NOT syntropic137)
**Branch:** to be created, off `main`. The source branch is `feat/observability-exporter-primitive`.
**Status:** ready-to-start (nothing cut yet)

> This handoff lives in the syntropic137 repo because the agentic-primitives
> submodule checkout is at a detached HEAD. The work itself happens entirely in
> agentic-primitives.

## Purpose & Vision

`AgentParadise/agentic-primitives#256` is a draft PR carrying the LangFuse
observability arc. It has been idle since 2026-07-16 and cannot merge as-is: it
is 980 files / +72,749 lines, and its base is another feature branch on the
**tmux** stack, which was abandoned as an execution substrate on 2026-07-22.

The goal is not to merge it and not to discard it. Roughly 6,350 lines inside it
are live, valuable, and have no dependency on tmux - an MCP server, operational
scripts, self-hosted LangFuse infra, and two ADRs. Extract those onto a fresh
branch off `main`, open one reviewable PR, then close #256.

This unblocks OKR bead `okrs-51p.14` ("close PR #256 review loose ends and
merge"), whose entire definition is currently "merge #256."

## Current State

- **Nothing has been cut.** No branch, no cherry-pick, no PR.
- `okrs-51p.6` (the parent "universal Rust observability exporter" KR) was
  **closed as descoped** on 2026-08-14. The universal-exporter ambition was
  already retired on 2026-07-14 in favour of official harness-native LangFuse
  plugins; ADR-039 in this very PR is the record of that decision.
- #256 is still OPEN and draft, base `feat/itmux-env-credentials`.
- The agentic-primitives submodule under syntropic137 is at detached HEAD
  `944e4b5` with an unrelated dirty `providers/workspaces/claude-cli/Dockerfile`
  and untracked `docs/proposals/`. Do not build the new branch from that
  checkout - clone or fetch fresh.

Next actions, in order:

1. Fetch `origin/feat/observability-exporter-primitive` and `origin/main`.
2. Branch off `main` (suggested: `feat/observability-langfuse-tooling`).
3. Bring over the 27 keeper paths listed below (checkout-from-branch is simpler
   than cherry-picking commits - the history is tangled with the itmux base).
4. Run the repo gates, open the PR, leave the merge to the human.
5. Close #256 with a comment pointing at the replacement PR.

## Files Affected

**Total: 27 files, ~6,350 added lines.** Get them with
`git checkout origin/feat/observability-exporter-primitive -- <path>`.

Plugin (the main artifact, standalone, no tmux dependency):

- `plugins/observability/mcp/langfuse_server.py` - 1,790 lines. LangFuse MCP server: trace query, score write-back, learning-loop reports. This is the piece with the most value.
- `plugins/observability/skills/langfuse-learning-loops/SKILL.md` - the agent-facing skill
- `plugins/observability/scripts/langfuse-backfill-claude-chunked.py`
- `plugins/observability/hooks/handlers/observe.py`
- `plugins/observability/.claude-plugin/plugin.json`, `README.md`, `CHANGELOG.md`

Operational shell (standalone, portable):

- `scripts/langfuse-observability-doctor.sh` - 440 lines, readiness/diagnostics
- `scripts/langfuse-backfill.sh`, `langfuse-local.sh`, `langfuse-repair-codex-costs.sh`, `langfuse-model-pricing.sh`
- `justfile` - 49 added lines wiring the above

Self-hosted infra (relevant to OKR beads `okrs-51p.11` LangFuse Ops and `.12` Turnkey Install):

- `infra/langfuse/self-hosted/` - `deploy.sh`, `compose.private.yaml`, `README.md`, `tailscale/langfuse-acl-snippet.jsonc`
- `infra/langfuse/model-definitions/gpt-5.5.json`

Docs (ADR-039 in particular should land regardless of everything else):

- `docs/adrs/038-modular-agent-observability.md`
- `docs/adrs/039-official-langfuse-plugins-canonical.md` - records the decision to drop direct Rust OTLP in favour of official plugins
- `docs/runbooks/langfuse-observability.md`, `docs/guides/langfuse-observability-setup.md`
- `docs/plans/2026-07-07-observability-primitive-{implementation,completion-audit}.md`, `docs/plans/2026-07-13-observability-pr-stack-merge-checklist.md`
- `docs/handoffs/20260713-handoff_langfuse-central-flywheel.md`

**Explicitly DROP - 22 files, ~7,545 lines** under
`providers/workspaces/interactive-tmux/driver-rs/`: `src/langfuse.rs` (3,308),
`src/main.rs` (1,177), `src/run/harness_observer.rs` (799),
`src/run/observability.rs` (558), `src/run/workspace_executor.rs` (391), plus
`Cargo.lock`, tests, contract schema, README.

**Do not bring the experiment folders.** 931 files / 58,854 lines under
`experiments/2026-07-0*` and `2026-07-10--langfuse--*`. They are trace dumps and
run logs - real evidence, but they are the single reason the PR is unreviewable.
If the human wants them preserved, land them as a separate evidence-only commit
straight to main; nobody needs to review a JSON trace dump.

## Rationale & Key Decisions

**Why not just merge #256.** Its base is `feat/itmux-env-credentials`, a branch
in the tmux stack. Merging #256 requires merging that base first, which drags the
abandoned tmux substrate into main. There is no way to land #256 without also
landing work that was deliberately dropped.

**Why not close #256 outright.** That was the first recommendation this session
and it was **wrong** - made before looking at the PR's composition. Closing it
would throw away the 1,790-line MCP server, the operational scripts, the
self-hosted LangFuse infra, and both ADRs, none of which touch tmux.

**Why the Rust gets dropped rather than lifted.** The `driver-rs` LangFuse code
lives inside the interactive-tmux driver crate. It could be extracted into a
standalone crate, but the capability it provides (querying LangFuse) is already
covered by `langfuse_server.py` and the shell scripts, which are portable and
need no extraction work. Lifting ~6,200 lines of Rust to duplicate a capability
that already exists in Python is not worth it. Retiring the direct Rust exporter
is exactly what ADR-039 decided.

**Why checkout-from-branch rather than cherry-pick.** The commit history on
`feat/observability-exporter-primitive` interleaves keeper changes with itmux
driver changes across the same commits (e.g. `5a2589d` refactored `main.rs` and
`langfuse.rs` together). Cherry-picking commits will pull tmux code with it.
Take file paths, not commits, and write one clean commit.

## Do's and Don'ts (learned this session)

- **Do** double-check which repo a number refers to. `#256` exists in both
  repos: in agentic-primitives it is this observability PR; in syntropic137 it
  is an unrelated closed health-endpoint fix. Easy and expensive to confuse.
- **Do** treat ADR-039 as load-bearing. It is the written record of the
  descoping decision that closed `okrs-51p.6`. If nothing else lands, land that.
- **Don't** count the PR by file or line totals. 81% of #256 is experiment
  evidence; the "980 files" framing made this look like a week of untangling
  when the real code surface is 27 files.
- **Don't** build from the syntropic137 submodule checkout. It is detached at
  `944e4b5`, behind main, and dirty.
- **Don't** cherry-pick `5a2589d` or its neighbours. See above.

## Important Context to Keep in Mind

- Ordering: the new PR must be cut and green **before** #256 is closed, so the
  keeper code is never only-in-a-closed-PR.
- `plugins/observability/mcp/langfuse_server.py` was validated live on
  2026-07-10 against 36 real traces (Claude and Codex), recovering
  model/token/cost/tool data and round-tripping score write-back. One known gap
  recorded then: combined `trace_id` + `name` score filtering returns zero rows,
  so the CLI/MCP must fetch then filter locally. That is a live bug in the file
  being moved - carry it forward as an issue, do not silently fix it in the
  cherry-pick PR.
- LangFuse credentials/keys are **not** in these files and must not be added.
  Real values live outside the repo; `scripts/langfuse-observability-doctor.sh`
  is the intended way to verify an environment.
- After the PR merges, bump the agentic-primitives submodule pointer in
  syntropic137 as a separate change.

## Suggested Skills

- `sdlc:git-worktree` - cut the branch in an isolated sibling worktree; the
  submodule checkout is detached and dirty, so working in place will hurt.
- `sdlc:git` - branch, push, PR lifecycle.
- `sdlc:commit` - conventional commits; this repo uses cog-verify style gates.
- `delegating-to-codex` - the human requires a cross-model codex review pass on
  any PR before merge, and that review must include a concrete fix
  recommendation, not just findings.

## References

- https://github.com/AgentParadise/agentic-primitives/pull/256 - the source PR (draft, base `feat/itmux-env-credentials`)
- `docs/adrs/039-official-langfuse-plugins-canonical.md` (on the source branch) - the descoping decision
- OKR bead `okrs-51p.14` - "LangFuse PR stack: close PR #256 review loose ends and merge"; this work is its definition of done
- OKR bead `okrs-51p.6` - closed 2026-08-14 as descoped; its comment trail carries the full arc
- OKR beads `okrs-51p.11` / `okrs-51p.12` - LangFuse Ops and Turnkey Install; consumers of `infra/langfuse/self-hosted/`
- OKR board: http://localhost:3035 - protocol at `GET /agents.md`
