# Handoff: orchestrating the syn137 queue and setting priorities

**Date:** 2026-09-18
**Repo:** git@github.com:syntropic137/syntropic137.git   **Branch:** `main` (orchestration happens against `main`; this doc landed via `docs/handoff-queue-orchestration`)
**Status:** in-progress - v0.29.1-beta.2 deployed to the VPS, 4 executions in flight, 17 PRs open

## Purpose & Vision

You are running the development loop for Syntropic137 **using Syntropic137**. The platform dispatches agentic workflows at its own GitHub issues, you review what comes back, and you merge what holds up. Dogfooding is the point: every defect you hit is a defect a user would hit, and the loop only earns its cost if findings become filed issues rather than worked-around annoyances.

The operating cadence is in the `/loop` prompt the owner re-issues each cycle. This document carries what that prompt cannot: the judgement behind it, and the specific ways this system lies to you.

## Current State

**Deployed:** `v0.29.1-beta.2` on the VPS (`syn-api`, `syn-gateway`). Carries #1327, the fix for the TASK_RESULT regression that cost $316 over 34 runs.

**Verified working:** #1327's fix. The unreadable-TASK_RESULT failure in `implement` was 39% of spend before the beta.2 deploy (18 runs, $155.14) and has not recurred since it (deploy at 18:44:24Z, confirmed from the host).

**Not verified working:** delivery. `exec-bdba3a81d70b`, previously cited here as proof, passed premise, implement and verify, then **failed at `open_pr`** and delivered nothing. It is an instance of #1358, not evidence against it. Post-deploy, 1 of 8 finished runs delivered (12%), and 6 of the 7 failures died at `open_pr` ($60.82, 83% of post-deploy loss). Fixing the early failure is what exposed the later one.

**In flight:** #1311, #1305, #1298, #1292.

**Blocked on the owner** (do not merge these yourself):
- **#1351** - version bump to 0.29.1-beta.2. Touches `packages/syn-shared/pyproject.toml`. Until it merges, `main` advertises beta.1 while the VPS runs beta.2.
- **#1349 vs #1331** - two competing branches for #1295. Only one should land; #1349 looks like the fuller fix.
- **syntropic137/event-sourcing-platform#307** - unblocks #1329.

**Next priorities, in order.** The owner confirmed performance and failure fixes come before new features. Revised after measuring post-deploy:
1. **#1358 rework loop** - live on the VPS, source in PR #1361. Validate it: no run has yet reached the case it exists for (verify finds a blocker, fix repairs it).
2. **Step-level retry** - #1344 (codex blip) and #1347 (phase timeout). The beta.3 content. See the correction under "Rationale" for why its share of loss is now about 10%, not 26%.
3. **#1318** - a projection rebuild starves all 24 other projections. Land it before beta.3 if beta.3 carries a projection version bump; see "Important Context".
4. **#1345** - ships the `agent_events` index through migrations rather than by hand.
5. Then the rest of the merge queue: #1346, #1348, #1325, #1330, #1314.

## Files Affected

This handoff adds one file. The orchestration itself touches no source; it merges other people's work.

- `docs/handoffs/20260918-handoff_queue-orchestration.md` - this document.

## Rationale & Key Decisions

**Why the merge gate is "green AND cross-model certified AND no CODEOWNERS path".** Each clause caught a real failure. Green alone let a stale PR through whose green described a tree 62 commits behind. Cross-model review caught a fix that was mechanically correct but whose *documentation* claimed a capability that was not provisioned (#1317). The CODEOWNERS clause exists because those paths change how the thing deploys, and a wrong merge there is not revertible by a revert.

**Why priorities are cost-ranked, not frequency-ranked.** The most frequent failure is usually the cheapest, because it fails early before any expensive phase ran. The one worth fixing first dies *late* and discards work that already succeeded. A class that happened twice and cost $27 outranks one that happened nine times and cost $3. Every failure tally you produce should report both, and rank by cost.

**Why "retry the step, not the run" is the highest-leverage fix.** Measured across 59 failures since the beta.1 deploy: 63% was one regression (now fixed), and the next 26% ($128) was two instances of the same missing feature - a transient external condition destroying an entire execution rather than the step it hit. Landing #1344 and #1347 removes a quarter of the loss without fixing any new bug. That distinction - *cost shape* rather than bug count - is what makes the product feel unusable, and it is the right thing to argue for.

**Correction, measured after the beta.2 deploy:** the 26% was a share of a loss dominated by the TASK_RESULT regression. With that fixed, the retry class was 1 run and $7.50, 10% of post-deploy loss, and #1358 was 83%. Retry is still the right beta.3 content. It is no longer where most of the money goes. A share of loss changes whenever a larger class is fixed, so re-measure after every deploy before ranking by it.

**Why a version bump is not a release.** `docs/deployment/test-deploy.md` is the runbook. A test deploy moves images to a host and produces no git tag, no GitHub Release, no npm publish. Seven `v0.28.0-beta.*` prereleases were once created in 48 hours, one per test deploy, none marking anything a reader cared about. Build, transfer, repoint, recreate. Nothing else.

## Do's and Don'ts (learned this session)

- **Do: check for a merged PR before dispatching at an issue.** Four of twelve candidates I picked were already fixed - the issues had simply never been closed. That cost ~$8.50 before I added the check and saved ~$8 on the next batch. `gh pr list --search "<issue-number>" --state merged`. A merged PR may also be a *partial* fix (#1253), in which case put what remains in the dispatch prompt.
- **Don't: dispatch into a build you have measured as broken.** I kept the queue at five for hours against a build failing 35% of runs, and reported the deploy need as a one-line footer. That converted a bug into a $488 bill. If you measure a live failure rate, stop dispatching and escalate loudly in the first paragraph.
- **Do: read the ref, not the working tree.** The main repo directory is **bare** and worktrees sit on stale branches. Use `git show origin/main:<path>` and `git grep <pattern> origin/main -- <path>`.
- **Don't: trust a PR's green.** `MERGEABLE`/`CLEAN` describes a textual merge. Merge `origin/main` in, re-run the suite on the merged head, and re-read any commits written after the last review.
- **Do: verify a deploy with a run that finishes.** The runbook says watch a *phase* reach `running`. That proves the workspace built and nothing else - it was green for the entire window the beta.1 regression was destroying runs. Watch a run **complete and report**.
- **Don't: run `just fitness-invariants` or the pre-push hook casually.** See #1343: it writes commits into the invoking repo and force-moves real branch refs, **including `main`**, while printing "706 passed". Snapshot `git rev-parse --all` before and after, and repair from reflog if they moved. Push with `--no-verify` and validate by hand until #1348 lands.
- **Do: keep an instrument that does not depend on projections.** When the read path is blind, query the event store directly on the host:
  ```
  ssh root@<vps> 'docker exec syn137-timescaledb psql -U syn -d syn -t -A -F"|" \
    -c "select event_type, to_timestamp(timestamp_unix_ms/1000)::time from events \
        where aggregate_id like '"'"'%<exec-suffix>%'"'"' order by global_nonce;"'
  ```
  This is the fallback #1319 says does not exist. It is how beta.2 was verified.
- **Don't: put backticks or apostrophes in a double-quoted `gh` comment body.** The shell mangles them. Write the body with a quoted heredoc (`<<'BODY'`) piped to `--body-file -`, or to a file first.
- **Do: distinguish a correct refusal from a platform failure.** An agent that reports it could not do an impossible task has not failed the platform. Both currently surface as `failed` with a red badge, which makes the system look worse than it is and inflates every failure number. Count them separately.

## Important Context to Keep in Mind

**The read path goes blind after any projection version bump.** A `get_version()` change makes the coordinator replay that projection from zero, and while it does, the other 24 projections **stall** - they stop advancing entirely. Symptoms: new executions never appear, `status_counts` has no `running` bucket, and `GET /executions/{id}` returns **404 "Execution not found"** for records the list endpoint is serving on the previous screen. Nothing is lost; it catches up at roughly 700 events/min. This is #1318, and it lands precisely when you are trying to verify a deploy. Reproduction is on the issue.

**The drain check is first, last and unskippable.** Read `status_counts` from `?page_size=1`, not a page of rows - the counts are tallied over the whole collection before the status filter applies. Any key outside `{completed, failed, cancelled, interrupted}` means work is in flight. Re-run it **immediately before** recreating containers, not at the start of the deploy; a check run an hour earlier is worth nothing.

**`can_open_pr` is broken**, so runs that do all the work then die at `open_pr` leave a complete branch with no PR. Sweep for branches ahead of `main` with no PR each cycle and open them by hand. Three were recovered this way in one cycle (#1345, #1346, #1347).

**Exit-code semantics are backwards from intuition.** A negative code (`-11`) means the **local** process was killed by a signal. A contained process killed by signal N returns positive `128+N`, so an in-container segfault is `139`. #1295 exists because this was got wrong.

**Never dispatch at #1026, #1083 or #1232** - owner design calls. **Never push to `.github/workflows`.**

**Every dispatch prompt must carry** the 3600s budget warning, "push your first commit within 15 minutes", the scope guard ("same bug elsewhere fix it, different bug note it in one line"), and the mutation requirement - a new test must be shown able to fail, and new Python test files need the `unit` marker (`architecture` under `ci/fitness/`). An unmarked module collects zero tests and the gate goes green over nothing.

**Report honestly.** When a number you gave turns out wrong, correct it with the basis. I told the owner a rebuild would take two hours from a single one-minute sample taken while it was still warming; it took twenty. State whether a number is measured or inferred, every time.

## Suggested Skills

- `delegation:delegating-to-codex` - the cross-model review pass before every merge. Wrap in `gtimeout`; codex has no built-in budget cap, and a wedged run produces zero bytes indefinitely (one wedged for 45 minutes this session and had to be killed and done by hand).
- `sdlc:git-worktree` - never switch branches in the main directory; it is bare and other worktrees share its refs.
- `superpowers:systematic-debugging` - before proposing a cause for any new failure class.
- `experiments:running-experiments` - when a claim about failure rates needs to be settled rather than argued.

## References

- `docs/deployment/test-deploy.md` - the deploy runbook. Read all of it before touching the host.
- `docs/release-process.md` - what a real release is, versus a test deploy.
- `workflows/sdlc/retrospective-v1/` - the retrospective meta-workflow (merged as #1334). Its `classify` phase defines the cost-ranking and platform/task/correct-refusal split used above; its `autopsy` phase enumerates six shapes of passing-but-blind gate.
- https://github.com/syntropic137/syntropic137/issues/1318 - rebuild starves all projections. Top priority.
- https://github.com/syntropic137/syntropic137/issues/1343 - fitness suite force-moves the invoking repo's branch refs.
- https://github.com/syntropic137/syntropic137/issues/1342 - read-only repository mounts; the missing half of #1308.
- https://github.com/syntropic137/syntropic137/issues/1285 - the `can_open_pr` bug behind stranded branches.
- https://github.com/syntropic137/syntropic137/issues/1319 - no fallback instrument when the API is the thing being repaired.
