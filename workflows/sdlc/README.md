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

The tool half of this is declared but NOT yet enforced, in two different ways.

For the Claude phases, `allowed_tools` maps to `--allowedTools`
(`apps/syn-api/src/syn_api/_wiring.py:285`), which governs auto-approval rather
than availability (#964). The declarations state intent and begin enforcing
when #964 lands.

For the codex review phase there is no enforcement at all, and no way to ask
for it: `_build_codex_command` hardcodes `--sandbox danger-full-access` and
accepts only a prompt and a model (#1009). The container is still the isolation
boundary, so this is not a host-security matter -- but it does mean the review
phase can WRITE to the workspace whose artifacts are collected, so a reviewer
could rewrite the document it was asked to critique. For a phase whose entire
value is an independent second opinion, that is the property that matters.

## Planned families

| directory | output | status |
|---|---|---|
| `research-plan/` | an implementation plan | built |
| `implement/` | a PR implementing an approved plan | next |
| `tech-debt/` | a prioritised debt register | planned |
| `architecture/` | boundary and coupling findings | planned |
| `devops/` | merges, conflicts, release mechanics | planned |

Each is separate because each wants different skills and different tools. A
single "do software" workflow would need the union of every tool, which is the
opposite of the focus this structure exists to create.
