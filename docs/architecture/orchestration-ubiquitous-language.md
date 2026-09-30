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

## Admission

The decision that an operation may proceed, recorded before any work begins.
Resuming is admitted or refused against the original's recorded state; the new
Execution is then created and started by a background processor.

An admitted Resume is not a started one. The two are separate facts, and a
successful API response reports the first.

## Words we do not use

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
- **Branch.** Reserved, no meaning assigned. If a chat-style "branch from here"
  operation is ever wanted, this is where it gets defined.
- **Retry.** A Phase attempt within one Execution (`PhaseRetryScheduled`), never
  a new Execution.
- **Fork, in the process sense.** `GRPC_ENABLE_FORK_SUPPORT` and `os.fork` are
  unrelated to this vocabulary. Renames must not touch them.
