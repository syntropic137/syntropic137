# Declaration integrity: what enforcement changes on the deployment

**Date:** 2026-09-01
**Companion to:** commit `a6014786`, issue #1039, ADR-069
**Measured against:** the Mac mini deployment, 50 installed workflows, 116 phases

Wiring `allowed_tools` makes three previously-dead things live at once: the
Claude `--tools` restriction, the codex tool-policy refusal, and the #964
vocabulary validator. This file records what that changes for workflows already
installed, measured rather than reasoned.

Everything below is from the deployment's own API, not from reading YAML in the
repo. Stored templates are rehydrated from their historical
`WorkflowTemplateCreated` events and never see the YAML validator, so the repo
is not a reliable picture of what is installed.

## Summary

| Class | Phases | Workflows | Effect once enforcement is live |
|---|---|---|---|
| Tool name outside the vocabulary (`git`) | 11 | 4 | Execution refused, loudly |
| Codex phase declaring tools | 2 | 2 | Execution refused before provisioning |
| Declaration narrower than actual use | 4 | 2 | Phase silently loses a tool it uses |
| Non-sequential `execution_type` | 0 | 0 | Nothing. No stored template has one. |

## 1. Eleven phases declare `git`, which is not a tool

Workflows `8212f9d0` (CI Self-Healing), `f0eb911a` (PR Review), `b2f445b6`
(Code Review), `e6fbb8e1` (Release Preparation). Declarations are lowercase and
include `git`: `['bash', 'git', 'read']`, `['bash', 'git']`.

`git` is not a tool on any harness; it is reached through `Bash`. These
declarations predate #964 and bypassed it by being stored.

**Why this refuses rather than dropping the unknown name.** Dropping `git`
would restrict those phases to `Bash` and `Read` and remove everything else
they use. That failure looks like the agent got worse, and it would be
attributed to the model rather than to a bad declaration.

**Blast radius is nil.** These four workflows have no successful run history:
three have zero runs, one has a single failed run. Refusing them breaks nothing
that currently works and surfaces declarations that have been wrong for months.

**Fix:** drop `git` and correct the casing, e.g. `['bash','git','read']` becomes
`[Bash, Read]`.

## 2. Two codex phases declare tools codex cannot honour

- `selfhost-delegation-v1 :: build-and-delegate` - `[Read, Write, Bash]`
- `verify-v0270 :: r` - `[Read, Grep]`

Codex enforces a filesystem sandbox, not a tool vocabulary (ADR-069 section 3),
so the list was never applied. The refusal now fires at the execution boundary,
before a workspace is provisioned, instead of at dispatch after it is paid for.

**Fix:** remove `allowed_tools`, or move the phase to `claude`.

## 3. Four phases use tools they do not declare

THIS IS THE ONE THAT CHANGES BEHAVIOUR SILENTLY, and the only class here that
can degrade a workflow that currently works. Measured by comparing each phase's
declaration against the tools its own sessions actually recorded, across 45
completed phase-sessions.

| Workflow | Phase | Declared | Would lose |
|---|---|---|---|
| `sdlc-research-plan-v2` | `research` | Read, Grep, Glob, Bash | **Write** |
| `sdlc-research-plan-v2` | `revise` | Read, Grep, Glob | **Bash, Write** |
| `c1a58ac7` | `570a89ca` | Read, Bash, Write | Glob, Grep, WebFetch |
| `c1a58ac7` | `4b3d3fd3` | Read, Write | Bash |

`sdlc-research-plan-v2 :: research` is the clearest case: a research phase whose
deliverable is a written artifact, which does not declare `Write`. Under
enforcement it cannot produce its own output.

These declarations are not "too strict". They are WRONG, and they could only
ever have been wrong, because nothing has ever checked them. That is the defect
this track exists to end.

**Fix:** add the missing tools to each declaration before enforcement lands.

Note `Agent`, `TaskOutput`, `clone`, `checkout` and `unknown` also appear in
session tool records. They are observability labels, not `--tools` values -
`Agent` is the subagent tool the vocabulary spells `Task`. They are not
violations and no declaration needs to name them.

## 4. `execution_type` has zero blast radius

All 116 installed phases are `sequential`. The refusal of `parallel` and
`human_in_loop` cannot break an installed workflow. The execution-boundary
check is still correct to have - it costs nothing and closes the rehydration
path - but nothing needs migrating.

## Recommended order

1. Fix the four declarations in class 3. Without this, two actively-used
   workflows degrade the first time they run.
2. Fix or archive the four legacy workflows in class 1.
3. Fix the two codex phases in class 2.
4. Then land enforcement.

Classes 1 and 2 fail loudly and are safe to discover at runtime. Class 3 does
not, which is why it is first.
