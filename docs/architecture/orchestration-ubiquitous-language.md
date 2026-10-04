# Ubiquitous Language: orchestration

## Purpose

The vocabulary of the `orchestration` bounded context. These words have exactly
these meanings in code, in the API, in the CLI and in conversation. Where a term
here disagrees with any other document, this one is canonical.

This is the DOMAIN vocabulary. For event-sourcing patterns - Event, Aggregate,
Projection, Processor - see `es-glossary.md`. For the event store's own terms see
`lib/event-sourcing-platform/docs-site/docs/event-store/concepts/ubiquitous-language.md`.
A term belongs here when it names something this system's users talk about, and
there when it names a mechanism the platform provides.

Every bounded context has one of these, named
`<bounded-context>-ubiquitous-language.md`. See AGENTS.md, "Ubiquitous Language".

A word may mean something different in another context and that is not a
conflict: `resume` here is not `resume` in `github`, where it un-pauses a
Trigger Rule. One meaning per context is the rule, not one meaning globally.

---

## Execution

One run of one Workflow, identified by an `exec-` id, recorded as an event
stream. An Execution is never rewritten: its history is the record of what
happened, including how it ended.

Statuses: `not_started`, `running`, `completed`, `failed`, `cancelled`,
`interrupted`. The last four are terminal. There is no paused Execution - see
"Words we do not use".

## Phase

One step of a Workflow inside an Execution, with its own agent, model, prompt
and timeout. Phases run in a total order given by `order`, which
`WorkflowDefinition.from_yaml` guarantees is unique per Workflow.

A Phase is completed only when the Execution recorded it so. A Phase that
started and did not complete has no partial credit: there is no mid-phase
resume.

## Workflow

The definition a run is made from - its Phases and their configuration.
Mutable: installing a Workflow replaces it. An Execution therefore PINS what it
needs rather than reading the Workflow later.

## Resume

Continuing an Execution that DID NOT FINISH, by starting a new Execution that
inherits the Phases already completed and restarts at the first one that did
not.

Applies to `failed` and `interrupted` on request, and to `cancelled` only with
an explicit override - a cancel was a decision, and resuming past it needs a
fresh one.

The new Execution has its own id. The original stays exactly as it was,
including its terminal status, and records that it was resumed. One Resume per
Execution: "already resumed" is a fact about the original, so its stream's
optimistic concurrency is what makes two concurrent requests resolve to one.

`ResumeExecutionCommand` -> `ExecutionResumed` on the ORIGINAL's stream ->
`ResumeStartProcessManager` creates and starts the child. The event is the
decision; the start is a separate, idempotent step. Specified in ADR-014
section 7.

## Fork

Copying any Execution that has completed at least one Phase - INCLUDING a
`completed` one - into a new Execution that starts from a CHOSEN completed
Phase rather than from the first unfinished one.

Where Resume derives its starting point, a Fork is given one. Where Resume
carries the original configuration unchanged, a Fork exists in order to vary
something - a model, a prompt - against the same baseline.

**Not implemented.** Tracked as
[#1468](https://github.com/syntropic137/syntropic137/issues/1468), where it is
the substrate evals need: a fixed prefix and a varying suffix. The word is
reserved so the capability can be built without renaming anything. Until it
ships, an operation that continues unfinished work is a Resume and is called
one. `ci/fitness/code_quality/test_reserved_domain_words.py` fails if `fork`
reappears in this context before that issue claims it.

Until 2026-09-29 the code used `fork` for what this file calls Resume. See
ADR-014 section 7.

## Inherited Phase

A Phase a resumed Execution does not re-run, because the Execution it came from
completed it. Carries the artifact ids that Phase produced, and the id of the
Execution that actually produced them - which may be an ancestor further up a
chain of Resumes, not the immediate predecessor.

## Resume Phase

The Phase a resumed Execution starts at: the first Phase, in order, that the
original did not complete. Restarted from its beginning.

A Resume Phase that had already STARTED in the original may have pushed or
published something, and re-running it repeats that, so resuming such an
Execution requires the operator to acknowledge it.

## Pin

A fact an Execution records about itself at start so it can be reproduced
without consulting anything mutable: the full runnable configuration of every
Phase, and the commit each repository was at.

A Pin is why a resumed Execution runs what the original ran even if the Workflow
has been edited since.

An Execution's workspaces are checked out at its pinned commits, so the commit
it records is the code it ran on, however far a branch moves while it runs. A
resumed Execution's pinned commits are the original's, so it also runs on the
code the original ran on. A pinned commit no branch or tag of origin still
reaches refuses the Phase; it is never swapped for the branch's head.
(#1458, ADR-058.)

## Continued Branch

A branch a Resume Phase picks up rather than starting over: one the original's
failing attempt at that same Phase pushed to origin, confirmed at the resumed
Execution's start to be exactly where it was left, together with the PR open
from it. The Resume Phase is checked out at its head; every other Phase still
reads the pinned commit. Recorded on the resumed Execution's start. (#1513,
ADR-058.)

## Abandoned Branch

A branch a Resume Phase could have continued and deliberately did not, because
it was deleted, force-pushed or moved, its PR was closed, or the forge could not
be asked. Recorded with that reason on the resumed Execution's start; the Phase
starts fresh and is told so. Never a silent omission. (#1513.)

## Admission

The decision that an operation may proceed, recorded before any work begins.
Resuming is admitted or refused against the original's recorded state; the new
Execution is then created and started by a background processor.

An admitted Resume is not a started one. The two are separate facts, and a
successful API response reports the first.

## Eval

An experiment: a Goal, measured by runs that all start from the same Repository
Baseline. Recorded as its own event stream, the Eval aggregate, identified by an
Eval id (`eval-` plus a uuid when the caller supplies none). Its name and tags
describe it and stay editable for its whole life. Its Goal and Baseline are what
it measures, and Freezing fixes them.

An Eval does not list its runs. An Execution records which Eval it belongs to,
so attaching a run is one write to the Execution and the Eval's stream does not
grow with every run. (Evals plan, #967.)

## Goal

What an Eval sets out to measure, in a sentence or a paragraph. Trimmed, never
empty. A different Goal is a different experiment, so once the Eval is Frozen
the answer is a new Eval, not an edit.

## Repository Baseline

One repository, the ref a person asked for (`requested_ref`: a branch, tag or
sha), and the full commit sha that ref named when it was asked (`commit_sha`).
Every run of the Eval starts from `commit_sha`; `requested_ref` is kept so a
person can see what they asked for. A branch moving later changes nothing.

A Baseline is always resolved before it is recorded, through
`RevisionResolverPort`: one ref that cannot be resolved refuses the whole edit,
and an abbreviated sha never reaches an event. It wraps `RepositoryRef` and
never extends it: `RepositoryRef` says which repository, a Baseline says which
state of it. Each repository appears at most once in an Eval's Baseline.

A Baseline is not a Pin. A Pin is what one Execution records about itself as it
starts; a Baseline is what an Eval requires of every Execution it admits.

## Freeze

Fix an Eval's Goal and Baseline, permanently. Admission freezes an Eval before
the first run it admits, as a recorded `EvalFrozen` event, so an edit decided
against the unfrozen Eval loses on the stream version instead of slipping in
behind a run. Freezing a frozen Eval succeeds and records nothing. A frozen
Eval may still be renamed, retagged and archived. There is no unfreeze.

## Archive

Retire something without deleting it: a soft delete, for Workflow templates
and Evals alike. An archived Eval refuses every edit and refuses to be Frozen.
It stays readable, and its history and runs stay intact. Archiving an archived Eval
succeeds and records nothing.

## Words we do not use

- **Lock** (an Eval). The word is Freeze. "Lock" already means the skill and
  plugin lock files here, and an Eval is not locked against reading or
  against renaming.

- **Pause.** Deleted 2026-09-29. It recorded an event that nothing in the
  execution path observed - the processor checks `CANCELLED` and nothing else -
  so a paused Execution kept running, and zero such events existed in
  production across 26,917. Cancel is the mechanism that works. Pausing an
  Execution for real would require the processor to observe the status, which
  was never written. Note this is unlike `github`, where a paused Trigger Rule
  genuinely cannot fire.

  Gone with it: `ExecutionPaused`, `ExecutionResumed`, `ExecutionStatus.PAUSED`,
  `PauseExecutionCommand`, `ResumeExecutionCommand`, `ControlSignalType.PAUSE`
  and `.RESUME`, `POST /executions/{id}/pause` and its `resume` twin, and
  `syn control pause` / `syn control resume`. The control plane now carries
  `cancel` and `inject` only.

  **Admission pause is NOT this.** `POST /maintenance` pauses ADMISSION: the
  system stops accepting new Executions while a deploy drains. That is a
  property of the deployment, not of an Execution, and it stays. Where a
  to-do record reads `paused` (the resume-start list), it means the record is
  waiting on admission, not that anything was paused by an operator.
- **`can_open_pr`.** Retired after #1477. It was a Phase field that, from
  #1197, decided whether a Phase's token could open a pull request. #1477
  removed the token downgrade it controlled, so it decided nothing, and it was
  then dropped from the Phase and from Pins. Workflow YAML that still carries
  it loads, and validate and install report a warning naming the Phase; any
  other unknown key is still refused. Stored events that carry it replay
  unchanged, permanently. The retired keys are listed in
  `_shared/retired_phase_fields.py`; rejecting them at authoring time is
  #1502. There is no replacement: every Phase may open and comment on a PR.
- **Branch.** Reserved, no meaning assigned. If a chat-style "branch from here"
  operation is ever wanted, this is where it gets defined.
- **Retry.** A Phase attempt within one Execution (`PhaseRetryScheduled`), never
  a new Execution.
- **Fork, in the process sense.** `GRPC_ENABLE_FORK_SUPPORT` and `os.fork` are
  unrelated to this vocabulary. Renames must not touch them.
