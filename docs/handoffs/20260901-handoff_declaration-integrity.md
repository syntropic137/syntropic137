# Handoff: declaration integrity track (#1039, #967, #1034)

**Date:** 2026-09-01
**Repo:** github.com/syntropic137/syntropic137
**Branch:** `marketplace-gaps` (worktree `syntropic137_worktrees/20260901_marketplace-gaps`)
**Status:** research done, ADR proposed, implementation not started
**Coordinating session:** `syntropic137-f1` (ref 85bb3e). Reach it if a decision
below turns out to be wrong; do not silently work around it.

## Purpose

A workflow phase should declare what it needs, and the platform should either
honour that declaration or refuse it. Today four authored fields are validated,
persisted, projected, re-exported as YAML, and then dropped before execution.

The scope, ordering, and open questions are in
`docs/plans/20260901_declaration-integrity-track.md`. The design reasoning is in
`docs/adrs/ADR-069-harness-neutral-phase-definition.md`. Read both before
starting. This handoff carries only what those documents cannot: what was tried,
what was learned the hard way, and what will mislead you.

## Current state

- ADR-069 written and committed (`ce291cec`), status Proposed, not accepted.
- The plan document is committed alongside it.
- Nothing in the track is implemented.
- Four research analyses sit in the coordinating session's scratchpad under
  `research/`: the APSS recipe standard, our current phase surface, an empirical
  harness capability matrix, and prior art. They are not in the repository. Ask
  for them if you need the detail behind an ADR claim.

## The single most important fact

`ExecutablePhase` has exactly ONE production construction site:
`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/ExecuteWorkflowHandler.py:347-361`.

Anything not passed there is inert by construction. That is the whole bug, and
it is why the fix is small and the consequences are not.

`_build_agent_config_from_phase` at `:189-193` builds `AgentConfiguration` with
only `provider`, `model` and `allow_delegation`, so `allowed_tools` keeps its
default of `()`. The emit guard at `apps/syn-api/src/syn_api/_wiring.py:309`
therefore never fires and `--tools` is never passed to any phase.

## Do

- **Decide per field: apply, refuse, or delete.** The four fields are not one
  change. `allowed_tools` is mechanical. `argument_hint` probably should be
  deleted. `input_artifacts` changes behaviour for existing workflows.
  `execution_type: parallel` has no implementation, so wiring it without one
  converts a silent lie into a crash. Refusing it at authoring time is a
  legitimate and cheap answer.
- **Answer open question 4 in the plan by measurement**, against the Mac mini
  deployment: does any installed workflow currently depend on receiving
  artifacts it does not declare? That decides whether `input_artifacts` can be
  honoured or must be deleted. Do not decide it by reasoning.
- **Make the codex tools refusal reachable**, and move it from dispatch to
  workflow creation. `UnsupportedToolPolicyError` already exists and is correct;
  it is simply never reached. Refusing at creation means the author learns
  before provisioning is paid for.
- **Add the fitness function from ADR-069 D5**: a schema field may exist only if
  some code path applies or refuses it. This repository already runs fitness
  functions. This rule is what stops the class from recurring, and without it
  the next field will go inert the same way.
- **Work inside the Mac mini deployment where you can.** `syn` is configured
  against it. Dogfooding is the point.

## Don't

- **Do not trust a self-report as evidence.** This is the hardest-won lesson of
  the session and it cost four wrong conclusions in one day. A capability claim
  sourced from asking a model whether it has a tool is worthless; a model
  without a tool will narrate having used it. The reliable form is an artifact
  that only exists if the thing happened: have the agent write a file, then
  check the file. Apply this to your own verification too.
- **Do not test a component and report it as a fact about the system.** The
  `--tools` flag behaves one way at the raw CLI and another through the
  platform, which canonicalizes tool names before building argv
  (`packages/syn-shared/src/syn_shared/tools.py:50-58`). Test at the boundary
  your claim is about.
- **Do not vary two things in one test**, and always run a control. A control
  that also fails means you are measuring the instrument.
- **Do not widen scope into the recipe standard.** It is a separate track,
  blocked upstream on a missing Python loader (APSS #127). ADR-069 records the
  decision; nothing in this track depends on it.
- **Do not touch `.github/workflows/`.** The GitHub App deliberately lacks the
  `workflows` permission. Hand any such change back as a diff.
- **Never force push. Never rebase.** Merge commits only.
- **No em dashes in any file.** Plain hyphens. Project-wide rule.

## Important context that will otherwise mislead you

- **Two classes named `AgentConfiguration`** exist, in
  `orchestration/_shared/ExecutionValueObjects.py:35` and
  `orchestration/domain/aggregate_execution/value_objects.py:56`. There is also
  a duplicate pair named `ExecutionMetrics`. Check which module a consumer
  imports before editing; this has caused wrong-module edits repeatedly.
- **`/tmp` is mounted noexec in the workspace (#1042)**, so every `just`
  shebang recipe fails there, including `just qa-ci`. Direct `uv run pytest`
  works. Verification through `just` has to happen on a local machine until
  that is fixed.
- **Provisioning dies intermittently with `exit -11` (#1046).** That is the
  local `docker` CLI process receiving SIGSEGV, not anything in the container;
  the sign of the return code proves it. Two reproduction attempts failed. If a
  run dies at phase 1 with zero tokens, it is probably this, and re-running is
  the correct response.
- **A failed run's session may have no transcript (#1047)** because the agent
  never started. The message says the log was not found, which reads as data
  loss and is not.
- **Session operations are synthetic (#1034)**, so you cannot audit what a phase
  actually did from the platform's records. This is item 3 of the track. Until
  it lands, verify agent work by inspecting the repository state it produced,
  not by reading the session.

## Suggested skills

`superpowers:systematic-debugging` before proposing any fix.
`superpowers:test-driven-development` for the wiring itself.
`sdlc:git-worktree` if you need isolation.
`delegation:delegating-to-codex` for a cross-model review before opening a PR.

## References

- `docs/plans/20260901_declaration-integrity-track.md` - scope, order, open questions
- `docs/adrs/ADR-069-harness-neutral-phase-definition.md` - the design decision
- #1039 (the four inert fields, understated by two), #967 (execution tagging),
  #1034 (synthetic operations), #1052 (schema lineage), #964 (the closed tool
  vocabulary, whose validator currently enforces a restriction never applied)
