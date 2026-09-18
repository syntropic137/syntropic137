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

## What `timeout_seconds` actually bounds

`timeout_seconds` is an AGENT-WORK budget, not a wall-clock budget for the
phase. Workspace provisioning - the clone and the recursive submodule init - is
NOT inside it, and neither is artifact collection.

The path, in `WorkflowExecutionProcessor.py`:

    PROVISION_WORKSPACE and RUN_AGENT are separate to-do items (:358, :367).
    _handle_run_agent reads `phase.timeout_seconds or
    phase.agent_config.timeout_seconds` (:633) and passes it as
    `timeout_seconds=` to AgentExecutionHandler (:655), which hands it to
    `workspace.stream(...)` (AgentExecutionHandler.py:319).

So the timeout starts when the agent process starts, on a workspace that
already exists. Provisioning has its own separate budget:
`SYN_SETUP_PHASE_TIMEOUT_SECONDS` (default 120s,
`syn_shared/settings/config.py:355`), which bounds the setup script that does
the cloning.

**Two consequences when you tune one of these numbers.**

Raising a phase's `timeout_seconds` "to leave room for provisioning" buys
nothing - it was never spending any. A phase that is genuinely losing time to a
slow clone needs `clone_repos: false` or a larger
`SYN_SETUP_PHASE_TIMEOUT_SECONDS`, and raising `timeout_seconds` will not help.

Conversely, everything the AGENT does is inside the budget, including work that
feels like infrastructure: running the gates, `git push`, `gh pr create`. Those
belong in the arithmetic; the clone does not.

This has been got wrong three times: the `open_pr` note in
`implement/workflow.yaml`, the docstring of
`handlers/test_open_pr_needs_no_working_tree.py`, and the budget derivation in
`quickfix/workflow.yaml`. All three said provisioning ate a phase's budget.
All three were corrected against the call path above; state the model from
here rather than re-deriving it.

One caveat worth keeping: #1187's `open_pr` timeouts were real and are
recorded as ~one run in three. Removing the clone did not necessarily fix
them, because the clone was never inside the budget that expired. If that
phase still times out, look at the agent's own work.

## `delivers_repo_changes`: which phases own a branch

Every phase ends with the unpushed-work gate asking whether its workspace is
holding anything that dying would erase (#1184). `git status` is the only
evidence git has, and it cannot tell an agent's edit from a file a build tool
rewrote: on exec-e7e34af42553 a `bootstrap` phase ran `cargo check`, `Cargo.lock`
was rewritten, and the phase - which had done its job correctly, and whose
deliverable was a markdown report - was failed, its lockfile churn quarantined,
and a run resuming an hour of already-pushed work discarded (#1308).

So the phase declares it, and the gate reads the declaration instead of
guessing:

    delivers_repo_changes: false   # my deliverable is a report
    delivers_repo_changes: true    # my deliverable is a branch (the default)

**The declaration alone does not exempt anything, and today it exempts
nothing.** A phase that declares `false` still holds `Bash` and `Write`, so its
word about what it will do is not evidence about what it can do - and trusting
it would let an agent's real edit be destroyed by the very opt-out meant to
protect a lockfile. The gate therefore requires the declaration AND proof, read
from the mount table, that the repository is mounted read-only, so that a build
tool's churn is the only thing an uncommitted change could be.

**Production does not yet mount repositories read-only** (#1342). Until it
does, that proof never holds, the exemption never applies, and a phase whose
`cargo check` rewrites `Cargo.lock` fails exactly as it did before. Declare
`false` anyway - it is correct, and it starts working the moment the mount
lands - but do not expect it to prevent the failure today, and do not "fix" the
gate by dropping the mount check, which would reopen the hole above.

**Declare `false` on any phase whose output artifact is the deliverable** - a
bootstrap, a premise check, a review, a verify, a plan, an `open_pr` phase that
only reads a ref. Across the workflows here that is every phase except
`implement` and `quickfix`, which are the two that commit and push.

**It does not exempt commits.** A phase that declares `false` and commits
anyway still fails and is still quarantined: no build tool runs `git commit`,
so a commit is an authoring act under any declaration. The declaration decides
only what an UNCOMMITTED change means.

**Do not reach for it to quiet a phase that legitimately edits.** A
dependency-bump phase's lockfile churn IS its deliverable, and declaring `false`
there is how that work gets silently destroyed - which is the failure #1184
exists to prevent, arrived at from the other side.

The default is `true`, so a phase that says nothing keeps being judged
strictly. The cost of forgetting is a phase failed for a lockfile; the cost of
defaulting the other way would be every phase anyone ever writes losing the
gate.

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
