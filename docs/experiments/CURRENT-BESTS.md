# Current bests

**Living document.** Names the current recommended workflow / pattern / setting for each common task. Updated when a finding from any cycle promotes a new default or supersedes an existing one. The dogfooding runbook reads from here — it does NOT hardcode workflow IDs.

**How to read this:** each section names one task class, the current recommendation, the finding that justifies it, and any override conditions. If a recommendation is missing, default to "no current best — pick a shape and add the finding to the ledger."

**Workflow lifecycle — important:**

The IDs listed here are **starting points**, not a closed allowlist. Sessions running the dogfood loop can and should:

1. **Reuse** an existing workflow if it fits the task. This is the default. Existing workflow IDs are listed below per task class.
2. **Extend** by creating a sibling variant (`-v2`, `-routed-X`, etc.) when the existing shape is close but the experiment wants to vary one dimension. Document the dimension being varied in the new workflow's `description` field.
3. **Create** a new workflow when no existing shape fits the hypothesis. Examples: a probe that needs a different tool allowlist, a new phase shape under test, a one-off feasibility experiment.

After running, a finding lands in `FINDINGS-LEDGER.md`. If the finding shows the new shape beats the current best on the priority order (quality → time → cost), promote it: update this doc, mark the old recommendation `superseded`, link to the finding.

**Workflows ≠ best practices.** A workflow being defined on the platform doesn't make it recommended. Only entries in this doc carry the recommendation. The platform's full workflow inventory is observable via `GET /api/v1/workflows`; treat that list as "what's currently available," not "what's currently best."

**Don't proliferate without purpose.** If a probe creates `xxx-feasibility-v3-experimental-take-7`, prune it after the finding lands — either by superseding it cleanly in this doc or by removing the workflow record once the result is captured. The cycle's `BOTTLENECKS.md` is the right place to flag "we have N stale workflows we should clean up."

**How to update this:**
- A finding promotes a new default → add it here, mark the old one as `superseded`
- A finding invalidates a recommendation without replacing it → remove the recommendation, leave a stub explaining why
- Every change to this doc references the finding that drove it
- Append the change to the changelog at the bottom

**Last updated:** 2026-05-02 (cycle 4)

---

## Plan workflow

**Recommended:** `plan-multiphase-routed-haiku-opus-v1` — cheap models for explore/test/ship phases, frontier model on synthesis.
**Why:** F8 (cycle 3). Opus reasoning depth only earns its 5x cost premium on cross-perspective synthesis. The other phases tolerate Haiku without measurable quality loss. Validated on 2 different targets, cost ~$1.50/plan with quality matching all-Opus baseline.
**Override:**
- Highest-stakes design where every phase needs depth → all-Opus
- Tight budget, OK with shallower synthesis → all-Haiku
- Sonnet synthesis instead of Opus → ~40% cheaper but real quality drop on micro-conflict detection (F8 round 16)

## Implementation workflow

**Recommended:** `implement-from-plan-v1`
**Why:** Cell 13b validated end-to-end at $4.06 producing PR #752 (9/9 tests pass, pyright clean). Workflow shape covers bootstrap → implementation → tests → PR cleanly.
**Override:** none currently. Refinements pending: bake QA-aware test-fixture typing into the implementation prompt so output passes `just fitness-check` first try.

## Phase shape for multi-output tasks

**Recommended:** phase-per-artifact (one phase per intended output file, plus one synthesis phase).
**Why:** Cycle-4 tick-loop experiment. The platform captures only one primary artifact per phase (a regression against original design intent). N phases give N artifact slots; single-phase shapes lose all but one file regardless of how many the agent writes. P shape produced 7 captured artifacts at $0.075 per surfaced artifact vs F shape's 1 captured artifact at $0.43.
**Override:** if the workflow produces a single deliverable (one plan, one report), single-phase is fine. Multi-output is where the rule applies.
**Will be superseded by:** the per-phase artifact-capture fix (top priority on artifacts handoff). Once shipped, single-phase shapes can again surface multiple files and this recommendation drops.

## Orchestrator pattern (when N parallel workers needed inside one phase)

**Recommended:** `claude -p` children spawned with shell `&`, awaited with `wait`, captured via file redirect.
**Why:** Cycle-4 claude-p-feasibility v2. All seven tests passed: sync recursion, file capture, background+wait, parallel+wait with real concurrency (3 in 5s vs 3s for one), 2-level recursion, structured JSON output. ~$0.013/child on sonnet with cache warmup.
**Skeleton:** See `cycle-004/claude-p-feasibility/RESULTS-v2.md`.
**Mandatory gotchas:**
- Extract `CLAUDE_CODE_OAUTH_TOKEN` from `/proc/<parent>/environ` and pass as `ANTHROPIC_API_KEY` (not exported to child bash today; platform fix queued)
- Always `--output-format json`, NEVER `--output-format stream-json` (produces null bytes that crash event ingestion)
- Pipe child output through `tr -d '\000' | iconv -f utf-8 -t utf-8 -c` before any read

## Watching live execution

**Recommended:** SSE streaming via `GET /api/v1/sse/executions/{execution_id}` and `GET /api/v1/sse/activity`.
**Why:** Polling `/executions/{id}` works but is heavy (full execution doc each poll, no live progress). SSE was always there; just wasn't being used.
**Override:** none.

## Watching for execution completion (one-shot)

**Recommended:** SSE with a short script that reads stream events and exits when status reaches a terminal state.
**Override:** if SSE is unavailable, poll at 30s with backoff.

## Browser / E2E testing inside a workspace

**Recommended:** Playwright (Node or Python) with the 27 system libs workaround until the base image bakes them in.
**Why:** Cycle-4 playwright-feasibility. Confirmed working end-to-end. 40s cold-start today (1s npm + 9s chromium download + 30s lib download). Drops to ~10s with one Dockerfile change.
**Override:** none. Once the base image bakes the libs, the workaround drops.

## Workspace SDLC defaults

**Recommended cache redirection** (mandatory until base image is fixed):
- `UV_CACHE_DIR=/workspace/uv-cache`
- `UV_PROJECT_ENVIRONMENT=/workspace/.venv`
- `pnpm install --store-dir /workspace/pnpm-store`

**Why:** Cycle-4 SDLC probe. `/home/agent` is 128 MB tmpfs; default cache locations OOM during `uv sync` (pyright download alone fails). All workarounds eliminated by the three platform asks in #750.

## What's currently NOT recommended

- `--output-format stream-json` from `claude -p` children (null bytes crash event ingestion)
- Single-phase fan-out via parallel `Task` subagents for multi-artifact tasks (only the primary deliverable surfaces; the rest are silently dropped at the platform layer)
- Polling `/executions/{id}` when SSE is available
- Hardcoding workflow IDs in skills, runbooks, or external docs — they should reference this file

## What's pending (under experiment)

- Skill injection (#726) — once shipped, the orchestrator pattern can be encoded as an installable skill instead of inlined in every workflow prompt
- Artifact-capture fix — once shipped, "phase shape for multi-output" recommendation drops
- Browser-libs in base image — once shipped, browser-test recommendation simplifies to "just use Playwright"
- All three above are queued in `docs/handoffs/20260502_platform.md`

## Changelog

| Date | Change | Driving finding |
|---|---|---|
| 2026-05-02 | Initial population from cycle 3 + cycle 4 results | F8 (cycle 3), tick-loop / cron / claude-p-v1 / claude-p-v2 / playwright / sdlc (cycle 4) |
