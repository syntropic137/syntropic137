# SDLC workflows

Workflows that do the work of building software, as opposed to the `examples/`
(feature demos) and `validation/` (platform self-tests) trees beside them.

## Organisation

```
workflows/sdlc/
  <purpose>/                 one directory per workflow FAMILY
    workflow.yaml            the definition; id carries the version
    phases/<phase-id>.md     one prompt per phase, named for the phase
```

Three rules make this scale:

**1. The directory is the family; the id carries the version.**
`sdlc-research-plan-v1` and `-v2` live in the same directory, one at a time in
`workflow.yaml`, with superseded versions kept in git history. A workflow id is
immutable once it has run: executions reference it, and rewriting what `-v1`
means retroactively invalidates every comparison made against it.

**2. Phase prompt files are named for their phase id.**
`phases/research.md` belongs to the phase with `id: research`. Phase ids are
already load-bearing - a later phase reads an earlier one at
`artifacts/input/<phase-id>.md` - so tying the filename to the id means a rename
breaks loudly in one place instead of silently in two.

**3. One job per phase.**
A phase that researches AND plans stops researching early, because writing the
plan feels like progress. Separate phases also give each its own workspace,
tools, skills and cost line - which is what makes "did the review phase earn its
money?" an answerable question rather than a guess.

## Which implementation workflow: `implement` or `quickfix`?

Two workflows produce a PR. `sdlc-implement-v1` runs four phases with an
independent cross-model verify. `sdlc-quickfix-v1` runs one phase and has no
verification behind it at all.

**The test is not size. It is: is there anything to prove?**

A change whose correctness a reviewer confirms by LOOKING at the diff has
nothing to prove, and a verify phase can tell them nothing the diff did not.
A change a reviewer has to REASON about does, and that is the whole reason
implement and verify are separate phases in the first place (the measured
evidence is in `implement/workflow.yaml`).

Size is a bad proxy for this and gets the interesting cases backwards:

| change | verdict | why |
|---|---|---|
| a 200-line mechanical rename | `quickfix` | every line is the same edit, and reading it confirms it |
| a 3-line change to error handling | `implement` | you have to work out what happens now when it throws |
| pinning `vitest ^3.0.0` -> `3.2.6` | `quickfix` | the diff IS the specification |
| a one-word change to a projection | `implement` | it changes what a rebuild produces |

`quickfix` is for version pins, typos, dead links, config values, renaming a
constant, and deleting dead code something else proves unreachable. It is NOT
for behaviour, control flow, error handling, event schemas, projections,
security or auth, or tests that assert behaviour. Its prompt carries the full
lists, and it is required to stop and send the task to `implement` rather
than attempt anything whose correctness it cannot see.

When you are between the two, use `implement`. The tie goes to the slower
workflow, because the two failure modes do not cost the same: routing a
mechanical change through four phases wastes money, and routing a judgement
call through one produces an unreviewed behaviour change that looks reviewed.

That asymmetry is also why every `quickfix` PR is required to say in its body
that it had no independent verification phase. Reviewers here have calibrated
on cross-model-gated PRs; one that looks the same but skipped the gate borrows
trust it did not earn, and nothing in the diff reveals which workflow produced
it.

## Naming

    sdlc-<purpose>-v<N>        id
    "SDLC: <Purpose Phrase>"   name

`<purpose>` names the OUTPUT, not the activity: `research-plan` produces a plan.
A workflow named for its activity ("analyse", "review") tends to grow scope,
because any activity can always be done more.

## Composing, not repeating

Phases are meant to be lifted between workflows. A `cross-model-review` phase is
the same phase whether it reviews a plan, an implementation or an ADR - only its
prompt changes. When two workflows need the same phase, copy the prompt and
adjust it rather than parameterising one prompt to serve both; a prompt with
branches in it reads worse to a model than two direct prompts.

## Skills carry the standards

Phases declare skills so the standards travel with the work rather than being
restated in every prompt. Skills are pinned to a commit - never `@latest` - so a
run is reproducible and a comparison between two runs is meaningful.

The tool half IS enforced for the Claude phases. `allowed_tools` becomes a
single comma-joined `--tools` flag (`apps/syn-api/src/syn_api/_wiring.py:297`),
which governs tool AVAILABILITY, not merely auto-approval. #964 closed when
that changed: the field had previously mapped to `--allowedTools`, which
auto-approves tools the agent already had, and the command also carries
`--dangerously-skip-permissions`, so the declaration restricted nothing.

The codex review phase is a real exception, and it cannot be fixed in this
file. `_build_codex_command` hardcodes `--sandbox danger-full-access` and takes
only a prompt and a model (#1009), and codex rejects tool-NAME policies by
design, so the fix is a provider-neutral sandbox mode rather than an allowlist.
The container is still the isolation boundary, so this is not a host-security
matter -- but the review phase can write to the workspace its artifacts are
collected from, which means a reviewer can rewrite the document it was asked to
critique. For a phase whose whole value is an independent second opinion, that
is the property that matters.

## Planned families

| directory | output | status |
|---|---|---|
| `research-plan/` | an implementation plan | built |
| `implement/` | a PR implementing an approved plan | built |
| `quickfix/` | a PR for a change with nothing to prove | built |
| `tech-debt/` | a prioritised debt register | planned |
| `architecture/` | boundary and coupling findings | planned |
| `devops/` | merges, conflicts, release mechanics | planned |

Each is separate because each wants different skills and different tools. A
single "do software" workflow would need the union of every tool, which is the
opposite of the focus this structure exists to create.
