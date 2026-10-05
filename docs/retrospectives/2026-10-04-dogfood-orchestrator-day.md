# 2026-10-04 A day of building Syntropic137 with Syntropic137

## What happened

One orchestrator session (Claude, Opus) ran the flywheel deployment for about 32 hours (2026-10-03 18:00Z to 2026-10-05 02:00Z). It worked in 30-minute ticks: triage, dispatch `sdlc-implement-v3` runs, verify what they delivered, review with codex, merge, and cut betas. Two betas reached production (beta.5, finished by hand, and beta.6 in 313 s). An event-store release closed a silent event-loss path at its root, dashboard reads got 5-15x faster, and 39 PRs merged across four repos. Half of the 96 executions failed, mostly on the platform's own limits (the 60-minute phase deadline, restarts, transient errors) rather than on agent mistakes. The single largest idle period, about 3 hours, was the orchestrator's: it asked a blocking question while the owner was away.

## Timeline

Times are UTC. A handful of orchestrator log entries between 16:20Z and 19:15Z were stamped by hand and ran up to 40 minutes ahead. The times below come from GitHub, the deployment or command output, not those entries.

- 2026-10-03 18:37 - read models ~10 min behind; ProcessManager drains ran inline on the shared cursor (#1528)
- 2026-10-04 07:29 - API OOM at 512m (#1552), then event-store OOM loop during a rebuild (#1553); both limits raised to 2g
- 2026-10-04 ~09:40 - host disk 99%, Postgres `No space left on device` mid-run (#1560); old workspaces and images cleared by hand
- 2026-10-04 14:46 - #1558 merged (E1: /metrics and heatmap read a usage rollup)
- 2026-10-04 ~15:00 - orchestrator killed a running pit stop mid `compose up`; gateway down ~10 min
- 2026-10-04 15:54 - beta.5 pit stop fails: a one-time rollup backfill took ~2 min at startup, compose marked the API unhealthy, the gateway never started (#1575)
- 2026-10-04 16:00 - beta.5 finished by hand; admission reopened
- 2026-10-04 16:17 - event-store fix ESP #337 merged; 16:30-17:10 #1566, #1562, #1580 (E2) merged
- 2026-10-04 17:02 - ESP v0.16.0 published (a manual `gh release create`; merging the release PR alone publishes nothing)
- 2026-10-04 18:41-18:47 - every dashboard client stalled ~6 min, then all released together; logs could not say where (#1583)
- 2026-10-04 20:42 - headless Chromium + pinned Playwright merged to agentic-workspace (#33), after a codex finding added per-arch sha256 verification
- 2026-10-04 ~20:45 - orchestrator asked the owner a blocking question and waited; no dispatches for ~3 h
- 2026-10-05 00:14 - #1582 merged (slow startup no longer takes the gateway down)
- 2026-10-05 00:20 - beta.6 live in 313 s, including a 4-min replay of 57.8k events
- 2026-10-05 00:22 - agentic-workspace release with the browser (#35); syn137 pin bump in PR #1594
- 2026-10-05 00:25 - workflow reinstall: the CLI tried to archive `sdlc-implement-v3` from stale local history (#1588)

## Root cause

**The platform's limits were invisible until a run hit them, and the
orchestrator was not held to the platform's own standards.**

On the platform side, each failure mode surfaced only by failing a paid run:
- **Deadline:** 17 phases died at the 60-min deadline. Measured afterwards, 65% of phase time went to gates and waits: `preflight-agent` failed late on file length, its first run took 12-20 min and hit the 10-min Bash cap, and hand-rolled waits missed completion. Two fix phases had pushed their fix by minute 5 and minute 19, then timed out gating.
- **Restarts:** 8 runs were orphaned by API restarts. A deploy still needs an idle platform (#1310).
- **Transient errors:** these fail runs outright, with no retry. A dropped GitHub connection (#1593) and codex "model at capacity" each did.
- **Silent edges:** a start event committed out of order and was never applied (#1545), and a request stall left no timing evidence (#1583).

On the orchestrator side, the same class of error kept recurring:
- **Unverified state:** a stale password, a reviewed worktree that wasn't at the PR head, and log timestamps written from memory.
- **A command blocked by the repo's security hook:** about 90 times.
- **One blocking question:** it idled the platform longer than any outage did.

## What we changed

- ESP #334, #336, #337 + v0.16.0 - ProcessManager drains no longer stall the shared cursor, near-head projections no longer wait on a rebuild, and appends commit in global-nonce order per tenant, which closes the out-of-order-commit gap a live subscriber skipped (#1528, #1554, #1545)
- PR #1558, #1580 - dashboard reads from rollups and bounded queries (table below)
- PR #1581 - `preflight-agent` runs the CI fitness invariants that can run in a workspace (VSA, codegen, submodule and Docker checks still run only in CI)
- PR #1582 - one-time startup work no longer fails liveness; pit stop waits for readiness before reopening admission and prints recovery steps when a swap fails
- PR #1551 - fitness test: in-memory adapters and doubles it can recognise must refuse to construct outside test/offline (ADR-060 §5; detection limits and exceptions documented there)
- PR #1562, #1566, #1579 - evals step 3; server-side workflow search; `/repos` page and an honest updating state on list filters
- AgentParadise/agentic-workspace #33, #35 - headless Chromium + pinned Playwright, sha256-verified, root-owned, in the published images
- Orchestrator practice (outside the repo): `papercuts.md` with 58 entries and statuses; a scratchpad with a HUMAN REVIEW section, so questions never block; pinned-destination helpers instead of ad-hoc `curl`; adversarial codex review of the orchestrator's own changes, which caught two of its overclaims
- Issues filed for every unfixed finding: #1575, #1583, #1585, #1588, #1593 and others (26 in the window)

## Scorecard

Window: 2026-10-03 18:00Z to 2026-10-05 02:00Z. Compare future retros against these figures.

| Measure | Value |
|---|---|
| Executions started | 96 (43 completed, 43 failed, 3 cancelled, 7 running at close) |
| Failures: phase deadline (exit 124) | 17 |
| Failures: agent correctly refused a false premise or unreviewed commits | 9 |
| Failures: orphaned by an API restart | 8 |
| Failures: work held at phase end / codex capacity / transport / token / disk | 4 / 2 / 1 / 1 / 1 |
| PRs merged (syn137 / ESP / agentic-workspace / skills) | 26 / 6 / 3 / 4 |
| Issues filed (syn137) | 26 |
| Peak concurrent executions | 7 |
| Longest orchestrator-caused idle | ~3 h |
| Security-hook blocks on orchestrator commands | ~90 |
| Paper cuts recorded | 58 |
| Projection replay (beta.6) | 57.8k events in ~4 min |

Live read latency on flywheel. These are single requests with curl, not p95.

| Endpoint | beta.5 (2026-10-04 ~18:50Z) | beta.6 (2026-10-05 00:21Z) |
|---|---|---|
| `/executions?page_size=50` | 1.6 s | 0.20 s |
| `/sessions?page_size=50` | 3.2 s | 0.33 s |
| execution detail | (3.1-4.4 s before E1/E2) | 0.24 s |
| contribution heatmap | 2.7 s | 0.20 s |
| `/metrics` | 0.96 s | 0.17 s |

## Open follow-ups

- [ ] #1585 / PR #1586 - fail-fast, timed `preflight-agent` (the deadline is mostly gating)
- [ ] #1593 - retry transient errors in provisioning; treat codex capacity as retryable
- [ ] #1310 - hot upgrade: phase 0 items and ADR-072 in flight; deploys still need an idle platform
- [ ] #1588 - `syn workflow install` prunes from local CLI history
- [ ] #1594 - pin the browser-capable images; then UI tasks attach screenshots in verify
- [ ] #1595 - CODEOWNERS on trust boundaries only; split the justfile's release recipes into their own owned file; generate compose env passthrough
- [ ] Reverify should defer docker-only gates to CI on the same SHA (PR #1587)
- [ ] Repo workflow YAML drifts from the deployed definition (reinstall dropped `Skill`)
