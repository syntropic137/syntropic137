# 2026-10-13 Provider contract day

## What happened

The day shipped the EXP-V1-0006 0.2.0 provider operation contract across
three repositories: the standard (APSS#143), its models and a Docker
implementation in agentic-workspace (AW#45, AW#46, AW#47, AW#48, AW#49), and
the token-free load-test driver here (#1879). 32 executions ran between 07:40Z
and 17:25Z, for USD 102.80. Every PR went through the platform's own verify
(`sdlc-implement-v3` / `sdlc-reverify-pr-v1`, verify on codex) and then
through an independent second verifier. The second verifier blocked three
PRs the platform verify had certified: AW#47 (two findings), AW#48 (a
cross-repository caller break, waived to SYN-1) and AW#49 (two findings). It
also blocked #1808, which the platform verify had certified on 2026-10-09.
Eleven of the day's failures were the vendor's (5 Codex capacity, and 6 from
an old account's weekly limit). Three of those eleven were also the orchestrator's,
because the token injector was not recreated after the account changed.

## Timeline

Merge times are from `gh pr view`. Execution times are the window the
orchestrator recorded; the API was not reachable from the workspace that
wrote this, so they were not re-read.

- 07:40Z - first execution of the window
- 11:55Z - APSS#143 merged (provider operation contract 0.2.0)
- 12:52Z - AW#45 merged (process-tree cancel feasibility probe)
- 13:05Z - AW#46 merged (contract models and vendored schemas)
- 14:52Z - syntropic137#1879 merged (load-test driver and pass bar)
- 15:10Z - 0fa8c36 on AW#47: execute keeps stdout and stderr apart (second-verifier B1)
- 15:28Z - AW#48 merged (explicit WorkspaceRuntime), caller break waived to SYN-1
- 16:26Z - cfdb177 on AW#49: the replay withholds the recording's own TASK_RESULT
- 16:56Z - 948a913 on AW#49: CI runs the scripted_agent tests
- 17:07Z - 55f30bc on AW#49: a closing claude result always reports success
- 17:22Z - AW#49 merged
- 17:25Z - last execution of the window
- 17:31Z - AW#47 merged

## Root cause

The platform verify certified changes whose defects are visible in the diff,
without running anything:

| PR | Certified head | Defect | Fix |
|---|---|---|---|
| #1808 | ce532fef2 (2026-10-09) | flag-off path reads `started_at` before `settle()`; main settles first | 79aece192 |
| AW#47 | 681aa5c4 | `execute` merges stderr into stdout, so `stderr` is always empty, against plan §5.1 "callers keep their API" | 0fa8c36 |
| AW#49 | 4cbac7bf | the replay keeps the recording's own TASK_RESULT, and the reader settles by precedence, so the recording's verdict can win | cfdb177 |
| AW#49 | cfdb1774 | 74 scripted_agent tests that CI never runs (python-compatibility matrix omits the package) | 948a913 |
| AW#49 | 948a913 | an `is_error: true` closing result routes the profile's TASK_RESULT to the error reason: no verdict | 55f30bc |

They share a cause: each is a contract with a consumer outside the diff
(callers of `execute`, syntropic137's `VerdictReader` and
`_handle_result_event`, the CI matrix, main's start order). The verify agent
checked the change against itself and its own tests, not against the
consumer. Every one was then caught by a second verifier.

## Scorecard

Window: 2026-10-13 07:40Z to 17:25Z. Compare against
[2026-10-06](2026-10-06-merge-down-and-the-dropped-start.md). The 2026-10-06
retro's rows are kept unchanged. The orchestrator stored the execution counts
and spend; they were not re-read through the API, which was unreachable from
the workspace that wrote this retro.

| Measure | 10-06 retro | This window |
|---|---|---|
| Executions started | 116 (47 completed, 66 failed, 2 cancelled, 1 running) | 32 |
| Spend (sum of execution cost) | USD 525 | USD 102.80 |
| Failures: Codex capacity / quota | 29 / 3 | 5 / 6 (quota = the old account's weekly limit) |
| Failures: agent refused or stopped at a platform gap | 20 | 3 (correct refusals: scope gaps) |
| Failures: phase deadline (exit 124) | 8 | not recorded |
| Failures: OOM at the workspace cap (exit 137) | 2 | 2 exit 137, cause unknown (not confirmed as OOM) |
| Failures: orphaned by an API restart | 1 | not recorded |
| Failures: DNS (new row) | not recorded | 2 |
| Failures: orchestrator error (new row) | not recorded | 4: one duplicate dispatch (exec-74adee82f756); 3 of the weekly-limit failures (token injector not recreated), also counted under quota |
| PRs merged in syn137 | 39 | 1 (#1879) |
| PRs merged, all repositories (new row) | not recorded | 6 (APSS#143, AW#45, AW#46, AW#48, AW#49, syntropic137#1879) |
| Peak open PRs | 24 | not recorded |
| Issues filed in syn137 | 27 | not recorded |
| Production incidents | 1 | 0 recorded |
| Betas deployed | 6 | not recorded |
| PRs whose second verifier found a blocking bug | 4 of 4 | 4 of 7. Population: the distinct PRs the second verifier decided on in the window, each counted once. Blocked a head the platform verify had certified: AW#47, AW#48, AW#49 and #1808 (#1808's head was certified on 2026-10-09, before the window; its fix 79aece192 landed at 08:59Z, inside it, and it was then approved). Approved without a block: APSS#143, AW#46, #1879. AW#45 has no stored second-verifier decision |
| Escaped defects per merged PR (new row, learning-loop) | not recorded | not recorded. No count of the defects that escaped both verifiers exists, and the second verifier's findings are not a complete one: the stored figures (AW#47 2, AW#48 1, AW#49 2) and the three AW#49 fix commits cut as cases below do not agree, and nothing was re-read to settle it |
| Platform-verify escapes seeded as eval cases (new row) | not recorded | 5 cases (#1808 1, AW#47 1, AW#49 3), one per fix commit whose defect is visible in the diff. Not every second-verifier finding is a case: AW#47's second finding and AW#48's waived caller break are not |
| Cost per merged PR (new row) | not recorded | USD 17.13 (102.80 / 6) |
| Run failure rate, excluding vendor outages (new row) | not recorded | 8 of 21 (DNS 2, exit 137 2, refusals 3, duplicate dispatch 1, over 32 minus 11 vendor), if every execution started; the per-status split was not recorded |
| Owner minutes per PR (new row) | not recorded | not recorded |

AW#47 was merged at 17:31Z, after the window, so it is not in the merged count.
#1808 is still open.

## What we changed

- The five escapes are now eval cases, each pinned at the first parent of its
  fix commit (PR #1884):
  - `verifier-seed-v1` v7 adds `start-clock-read-before-settle` (#1808 at
    4e174c541, the parent of 79aece192; the certified head ce532fef2 is two
    commits earlier and `check` refuses it).
  - The new suite `evals/verifier-seed-aw-v1` covers AgentParadise/agentic-workspace:
    `execute-stderr-merged-into-stdout` (AW#47 at 681aa5c4),
    `replay-keeps-recorded-verdict` (AW#49 at 4cbac7bf),
    `scripted-agent-tests-not-in-ci` (AW#49 at cfdb1774) and
    `replay-error-result-drops-verdict` (AW#49 at 948a913), plus two clean
    controls (agentic-primitives #358, staged teardown, and #395,
    security-hardening runtime exposure). Every other mainline merge at least
    30 days old, back to #345, fails a control rule; the suite's v1 note lists
    each and why.
- #1881 - resume lineage: link a resumed execution to its parent and back.
- #1882 - Codex capacity failures retry in-phase, or auto-resume, with
  bounded backoff, instead of waiting for an orchestrator resume each time.

## Open follow-ups

- [ ] Run the A/B over `verifier-seed-v1` v7 and `verifier-seed-aw-v1` v1. The
  orchestrator launches it; no run was launched here.
- [ ] Re-read this Scorecard's execution and cost rows through the API, paging
  with `page_size`, and record the per-status split the failure rate needs.
- [ ] The AW#48 caller break was waived to SYN-1. That waiver is not an eval
  case, because there is no fix commit to cut one from yet.
- [ ] Recreate the token injector whenever the Codex account changes. Three
  failures today came from not doing that; it belongs in the orchestrating
  skill.
