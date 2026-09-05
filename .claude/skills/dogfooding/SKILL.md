---
name: dogfooding
description: Use when deciding WHERE to do work on Syntropic137 itself - "run this through Syntropic", "dispatch a workflow", "should this go in a workspace or local", "kick off a run on the Mini", "dogfood this", "build Syntropic inside Syntropic", "why did the agent's push fail", "can an agent run our QA", "the execution says completed but nothing shipped". Covers what a workspace agent can and cannot do, why `.github/workflows` pushes must come from the local machine, how to write a task prompt that does not repeat a known failure, and how to verify a run actually delivered. Do NOT use for PR/release mechanics (see `devops`), for using the `syn` CLI as an end user (see the syntropic137 plugin skills), or for authoring workflow YAML.
---

# Building Syntropic inside Syntropic

## Overview

Work on this repo defaults to running **through Syntropic on the Mini**, not on the
laptop. That is the point of the project: the fastest way to find what the platform
cannot do is to try to build the platform with it. Every capability gap recorded in
this file was found by a run failing, not by reading code.

One deliberate exception, and it is a security boundary rather than a defect: see
Principle 2.

## Outcomes we are looking for

### Outcome 1: the platform is exercised by its own development

Real work is dispatched to Syntropic rather than done locally out of habit.

- *Signal:* on any given working day, the most recent execution is hours old at most, not a day.
- *Signal:* capability gaps arrive as failed or degraded runs with an execution id attached, not as speculation.

### Outcome 2: agents never gain write access to CI

The GitHub App installation cannot modify `.github/workflows`, and nobody "fixes" that by widening the token.

- *Signal:* `workflows` permission stays off the installation, and workflow changes land in commits pushed from a human-controlled machine.
- *Signal:* a task that needs a workflow change is recognised BEFORE the work is done, not after a rejected push.

### Outcome 3: a blocker is scoped to what it actually blocks

A narrow failure does not silently become a reason to stop dispatching.

- *Signal:* after a run fails on a path restriction, the next dispatch happens the same session.

### Outcome 4: a run's outcome is verified, not read off its status

Delivery is confirmed against the artifact that was supposed to exist.

- *Signal:* claims like "the workflow fixed it" are accompanied by a PR number or a diff, never by `status: completed` alone.

### Outcome 5: a task is scoped to what a workspace can finish

The limits of the execution environment are known before a run is paid for, not
discovered at its last step.

- *Signal:* a task requiring Docker or a browser is either adapted or kept local, rather than dispatched and lost.
- *Signal:* when a capability gap is hit, it is recorded with the image it was measured against.

## Principles

1. **Dispatch by default, and dispatch several at once.** Executions are independent
   and the platform runs them concurrently; three parallel runs cost the same
   wall-clock as one. Reach for local work when the task is smaller than the cost of
   describing it, or when it touches the exception below.

2. **Anything touching `.github/workflows/` is pushed from the local machine, not by
   an agent.** The App installation deliberately lacks the `workflows` permission, so
   a push carrying a workflow change is rejected by GitHub with:

   ```
   refusing to allow a GitHub App to create or update workflow `.github/workflows/ci.yml`
   without `workflows` permission
   ```

   This is a posture decision, not a bug queued for repair. This is a public
   open-source project, and CI is where release credentials and publish rights live:
   an agent that can rewrite a workflow can exfiltrate secrets or publish artifacts
   without review. Granting the scope to unblock one task trades a standing security
   property for an afternoon's convenience. Tracked in #1024 so the decision is
   visible rather than folklore.

   In practice: have the agent make and verify the change, then apply and push the
   workflow part yourself. The agent's diff and its verification output are still the
   valuable half.

3. **Scope the restriction to the path it names.** It rejects pushes touching
   `.github/`; it does not restrict `packages/`, `apps/`, `docs/`, `justfile` or
   anything else. Reading it as "agents cannot push" costs a day of dispatching, which
   has already happened once.

4. **Say in the task prompt which failure this run must not repeat.** Agents here do
   good work and fail on the hop nobody described. Naming the specific prior failure -
   with the command that proves it - is worth more than another paragraph of
   requirements. A prompt that says *"a previous attempt recorded this on an event
   that is never persisted; verify with `git grep` before you build on it"* prevents a
   whole class of rework.

5. **Require pasted command output, not a summary.** "Tests pass" is unfalsifiable.
   The agent's report should contain the commands and their real output, so a claim
   can be checked without re-running everything.

6. **Confirm delivery against the artifact.** An execution reports `completed` when
   its agent finishes without crashing, including when the agent itself reported
   failure in prose (#1023). Before believing a run shipped, look for the PR, the
   branch, or the file. A $4.40 run has already reported three completed phases while
   producing nothing.

7. **Keep your own record of what you asked.** The execution does not store the task
   prompt (#1030), so the only record of the ask is wherever you wrote it. Until that
   is fixed, put the task text in the run log or the PR body.

## Anti-patterns

Observed while doing this, not hypothetical.

- **A four-hour gap with no executions while the laptop is busy.** Usually traceable
  to one blocked run being read as a general blocker.
- **A task prompt that lists requirements but not the trap.** The agent satisfies every
  stated requirement and lands on the unstated hop. The last three of these were a
  value written correctly and dropped one layer later.
- **`status: completed` quoted as evidence of delivery.** The status describes the
  harness, not the outcome.
- **A workflow change attempted inside a workspace.** Costs the full run before the
  push is rejected at the last step. Recognisable in advance: if the diff would touch
  `.github/`, split that part out before dispatching.
- **A unit test offered as proof that a value survives to the API.** It proves the two
  objects it constructs, not the wire between them. The persistence hop needs a test
  that drives the real handler with real repository plumbing.
- **Reading the workspace's `git status` as clean because a command "should not" write.**
  Verification commands have mutated tracked files here; capture `git status --porcelain`
  before and after.

## Recommended tools and practices (as of 2026-08-30)

### Outcome: the platform is exercised by its own development

- **`syn workflow run implement-from-plan -t "<task>" -R syntropic137/syntropic137`.**
  The installed implementation workflow: Bootstrap, Implement, Open Draft PR. Ladders
  up by making dispatch a one-liner, which is what makes it the default.
- **Dispatch two or three at once and monitor them together.** Ladders up by making
  parallelism the habit rather than an optimisation.
- **`syn execution show <id>` and `syn execution list`.** Ladders up by making a run's
  cost and phase state checkable without the dashboard.

### Outcome: agents never gain write access to CI

- **Split the workflow change out before dispatching.** Ladders up by keeping the
  permission boundary intact without blocking the work.
- **Keep #1024 open as the record of the decision.** Ladders up by making the posture
  auditable rather than tribal knowledge.

### Outcome: a run's outcome is verified

- **`gh pr list` after a run that was supposed to open one.** Ladders up by checking
  the artifact instead of the status.
- **Read the phase artifacts, not just the summary.** Agents here report failure
  honestly in the artifact text even when the platform records success. Ladders up by
  putting the honest signal in reach.

### Outcome: a task is scoped to what a workspace can finish

Measured on the pinned `omni-agent-workspace` image, 2026-08-30. Re-measure after
any `PINNED_DIGESTS` bump; these are properties of an image, not of the platform:

| capability | state |
|---|---|
| `just preflight` static gates | 15 of 17 pass |
| dashboard lint + `tsc -b && vite build` | works, 3004 modules |
| `pytest`, `pyright`, `ruff`, `vsa validate`, fitness suite | work |
| Docker daemon | **absent** - no root, cannot start `dockerd` |
| `check-default-workspace-image`, `check-pinned-image-channels` | fail, both need Docker |
| full e2e container stack | not possible, same reason |
| Playwright / headless Chromium | possible only after downloading 27 system libs (~40s); the image ships none (#1028) |

Ladders up by letting a task be scoped to what the workspace can finish, instead of
discovering the limit after paying for the run.

## References

- #1024 - the `workflows` permission decision and its options.
- #1023 - executions report `completed` when the agent reported failure.
- #1030 - executions do not record the prompt they were given.
- #1028 - the workspace image lacks Playwright's system libraries.
- `.claude/skills/devops/SKILL.md` - PR, version and release mechanics.
- `AGENTS.md` - `just qa-ci` and the pre-PR checklist that CI mirrors.

## Continual improvement

This skill is maintained in the syntropic137 repository:
https://github.com/syntropic137/syntropic137/blob/main/.claude/skills/dogfooding/SKILL.md

The capability table and the issue references are the parts that rot. When a run
finds a new limit, add it with the execution id that found it; when one of the
referenced issues closes, update the principle it supports rather than deleting
the reference, so the reasoning survives the fix.
