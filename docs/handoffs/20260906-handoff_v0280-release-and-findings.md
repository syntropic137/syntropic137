# Handoff: v0.28.0 release, and what a day of dogfooding surfaced

**Date:** 2026-09-06
**Repo:** syntropic137/syntropic137
**Branch:** main (`593c3c83`)
**Status:** v0.28.0 released and deployed to the VPS. 21 PRs merged. Backlog blocked on owner decisions.

## Purpose

Preserve the reasoning behind an unusually dense day: a release cut and deployed, 21 merges, and roughly a dozen defects found by running the platform on itself. The diffs and merge comments record *what* changed. This records *why* things are shaped as they are, which errors were made, and the traps that will otherwise be rediscovered.

## Current state

- **v0.28.0 released** (GitHub release, containers, `@syntropic137/cli` on npm) and **deployed to the VPS**.
- Verified on the running release, not inferred: runbook §8.1 passes on `/executions`, `/sessions`, `/artifacts` (`total` invariant under page size, windows narrowing strictly, paging reaching the last row); multi-repo confirmed by `docker exec`; a real workflow reaching bootstrap.
- Main is green. Deployment healthy, projection `lag: 0`.

**Open PRs, all blocked on the owner:**

| PR | why |
|---|---|
| #1226 | CODEOWNERS (`infra/`) — `release-local` build args. Head is self-certified. Only failing check is a Vercel rate limit. |
| #1218 | CODEOWNERS (`docker/`, `infra/`) — docs corrections |
| #1181 | CODEOWNERS (`infra/`) — pre-deploy drain check |
| #1083, #1026 | owner design calls, deliberately untouched |

## The one theme worth carrying forward

Nearly every defect found today was **a check that could not fail**, or **a step that reported success without the effect it claimed**. Same shape, ten-plus instances:

- a ratchet matching a literal string, so renaming `dict` → `Mapping` satisfied it (**45 untyped dicts in syn-api had never been counted**)
- a runbook checklist with a residual term that absorbed any shortfall, so a chip reading "completed 35" against a true 235 would have passed
- tests inspecting only rows that had already passed the assertion they made
- a completion check that never read the store head, so three stalled projections read as "done"
- a backfill appending an event with **no entry in `EVENT_HANDLERS`** — wrote, reported success, and no reader ever saw it
- a "no fabricated dates" test that passed while the script fabricated dates
- a fitness test claiming to measure every build path while blind to one Compose syntax

**The lever that works:** demand a mutation that proves the check bites, and require the assertion to run against the *external* oracle — the git remote, the read model, the built image — never the payload under test. The payload cannot be both the thing tested and the thing testing.

## Errors I made, so they are not repeated

1. **Read the wrong ref.** The repo's main working directory sits on `feat/workflow-validation-suite` (v0.26.0), not `main`. I filed **#1202** quoting code that had moved and been fixed a week earlier, and separately concluded a file "does not exist" when it does. Use `git show origin/main:<path>`. A dispatched phase caught it, stopped, and proved the premise false for $3.70.
2. **Broke the deploy with a local build.** `just release-local` omits `INCLUDE_DOCKER_CLI=1`, producing a `syn-api` with no docker CLI. Every execution failed at bootstrap while `/health` reported healthy. Fix in #1226; **verify a deploy by dispatching a real workflow**, not by reading a health endpoint.
3. **Recommended a memory cap from 14 samples.** Called 948 MiB "the peak"; it was the p90 of a bimodal distribution. True max is 2.1x that. Withdrawn on #1126.
4. **Wrote unsatisfiable specs twice.** Asked for git commit-push *authorship* (git does not carry it) and for a module move with nothing to move. Both produced correct-looking rejections of good work. On a second identical rejection, suspect the requirement.
5. **`git checkout --` during mutation testing** wiped an uncommitted fix. Commit first.
6. **Believed a rejected push had succeeded** by reading `tail`'s exit code, not git's. Verify the remote head.

## Traps that will bite again

- **`just check-version` reports "OK: All 11 files"** while `uv.lock` and three plugin schema `$id`s are stale. Fixed in #1224 (now all 15), but the *pattern* — a check narrower than the thing it certifies — is everywhere.
- **`open_pr` fails the run when there is nothing to do** (#1221). 4 of 100 runs. The refusal path is confirmed *working*; only the no-op path produces no deliverable. Likely needs a prompt change, and prompts are frozen.
- **A verify phase can write to and publish from the branch it reviews** (#1197). Four occurrences. `allowed_tools` is *not* the lever — codex has no tool-name concept (verified against 0.147.0). Only sandbox mode or credential scope can constrain it. **Do not change the sandbox casually**: `workspace-write` broke every codex phase in beta.5 and silently disabled the verify gate for ~70 minutes. Sandbox semantics are host-specific.
- **Same-named repos from different orgs** used to collide silently in `/workspace/repos` (bare names, no owner). Refused at provisioning now (#1225). `owner__repo` was never a rejected design — ADR-058 chose bare names without considering collisions, and the docs *invented* `owner__repo` as a fix that was never built. Moving to it is a migration touching `$SYN_ALL_REPOS`, the workspace prompt tree, `unpushed_work_guard`'s `find`, and ADR-058 itself.
- **A release can succeed while npx stays a version behind** (#1227). The sync opens a PR nothing asserts is merged.

## Measurements worth keeping

- **Memory (#1126):** 83 workspaces, 10,939 samples. `peak_anon` 1384 MiB, `peak_total` 3648 MiB, **`limit_hits` 0** — nothing has ever reached the 4 GiB cap. Distribution is bimodal *in page cache*, not in demand. Recommendation: keep 4 GiB, raise concurrency and watch `hit_max`; the first non-zero value is the stop signal. `ws-anon-sampler.service` is enabled across reboots and writes `/var/log/ws-anon-samples.tsv`.
- **Clone failures (#1153):** 55 consecutive clean runs since `storewarm`, P(zero by luck) = 0.0063. Criterion met. Left open because `storewarm` is a keepalive papering over a healthz cold-start, not a repair.
- **Bootstrap (#1192):** median 419s, max 1517s, **17.8x spread**, ~4.3 hours across 30 executions. Unpredictability, not slowness, is the problem.

## Do's and don'ts

- **Do** verify a deploy by dispatching a workflow. **Don't** trust `/health`.
- **Do** drain-check immediately before deploying, and don't dispatch while preparing one. Deploying through in-flight runs destroyed work once.
- **Do** read code with `git show origin/main:<path>`.
- **Don't** add anything to `fitness-exceptions.toml`. `_wiring` sits excepted at 1162 and grew *while* excepted.
- **Don't** edit `.github/workflows/` — the GitHub App lacks the permission by design on this public repo. Say what one-line change is needed and stop.
- **Don't** edit workflow prompts under `workflows/` — frozen as the baseline for a pending experiment.

## Suggested skills

`sdlc:git-worktree` for branch isolation; `delegation:delegating-to-codex` for cross-model review dispatch.

## References

- Release: PR #1057, tag `v0.28.0`
- Rollout constraints and the rollback `DECISION REQUIRED`: `docs/release-process.md`
- Test deploy: `docs/deployment/test-deploy.md`
- List-surface validation: `docs/testing/release-validation.md` §8.1
