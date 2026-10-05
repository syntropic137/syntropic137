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

## Review Verdict

What a reviewing Phase concluded about the change in front of it: `certified`
(nothing blocks it) or `blocked` (something must be fixed first). The Phase
REPORTS it, as `review_verdict` in its TASK_RESULT block; the Execution
DECIDES on it. `certified` ends the repair loop: every Phase before the
Workflow's final Phase becomes a Skipped Phase. `blocked`, or no verdict, runs
the next Phase by `order`. A word other than exactly `certified` or `blocked`
is no verdict - it never skips anything.

Not `success`. A Phase that finished a review that blocks the change
succeeded; its verdict is `blocked`.

## Skipped Phase

A Phase the Execution decided will never run, because a Review Verdict made it
unnecessary. Recorded on the `NextPhaseReady` decision as `skipped_phase_ids`.
Never started, never completed, never billed.

## Unresolved Findings

How a `completed` Execution ended when its last Review Verdict was `blocked`:
every repair round the Workflow allows ran, and the last review still refused
the change. Recorded as `review_verdict: blocked` on `WorkflowCompleted`, and
visible on the execution detail API. A `completed` Execution with
`review_verdict: certified` is a certified one; with none, nothing reviewed it.

A status, deliberately not: the run did not fail - every Phase did its job -
and the bound was the Workflow's own decision.

Continuable by a Resume. A `completed` Execution is resumable only when it
ended with Unresolved Findings, and then not at its first unfinished Phase
(there is none) but at its Repair Point: the Phase before the Review that
blocked it - the last round's fix. The Resume inherits every Phase before the
Repair Point and re-runs that round against the findings still open, then its
review and everything after. That fix already ran and may have pushed, so the
Resume must acknowledge external effects. A `completed` Execution that
certified, or that nothing reviewed, still has nothing to resume.

## Repair Point

Where a Resume of an Execution with Unresolved Findings starts: the Phase
immediately before the Phase whose `blocked` verdict the run ended on. Decided
by the aggregate from its replayed Review Verdicts (`ReviewRecord.repair_point`),
never by the caller.

## Delegation

A phase's agent handing part of its work to the **other** harness: a claude
phase to codex, a codex phase to claude. The delegate is a cross-harness child
that reports itself through the platform's `syn-delegate` shim; a harness's
own native subagents are not delegation. The provider alone decides where a
delegate goes, so a phase never names its delegate's harness
(`DELEGATION_TARGET_BY_PRIMARY`).

- **Delegation permission** (`agent.allow_delegation`): the agent MAY
  delegate. Both harnesses' auth is staged. Never gated: a permitted phase
  whose agent did the work itself completed.
- **Required delegation** (`agent.require_delegation`, `AgentConfiguration.require_delegation`):
  the phase MUST delegate. It completes only when a delegate to its
  **required delegate** - the other harness (`AgentConfiguration.required_delegate`) -
  reported success. A delegate to any other harness does not count. Implies
  the permission.
- **Delegation failure** (`DelegationFailure`): the typed account of a
  required delegation that did not happen - `not_attempted` (no delegate to
  the required harness), `failed` (every one failed or never finished),
  `unverifiable` (the record could not be read). Platform-observed, never the
  agent's word (#894).

## Workflow

The definition a run is made from - its Phases and their configuration.
Mutable: installing a Workflow replaces it. An Execution therefore PINS what it
needs rather than reading the Workflow later.

## Resume

Continuing an Execution that DID NOT FINISH, by starting a new Execution that
inherits the Phases already completed and restarts at the first one that did
not. Or one that finished with Unresolved Findings, restarting at
its Repair Point.

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

## Starting Checkout

The commit each pinned repository was actually found at once a Phase's
workspace was provisioned, read back from the workspace rather than taken from
the request, and verified against its pin before the agent is given the
workspace. A repository not at its pin is a Checkout Mismatch and refuses the
Phase. A Continued Branch is held to its branch instead of its pin, since its
head may legitimately be past the pin: it must be at origin's fetched head of
that branch, and that head must contain the pin, or it too is a Checkout
Mismatch. Recorded on every Phase's provisioning; the Execution's Starting
Checkout is the first provisioning's, even when that one recorded none. (#967.)

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

## Executor

The process role that runs Executions (`SYN_PROCESS_ROLE=executor`; `all`
runs it beside the API in one process). It Claims admitted Executions from the
Run Queue and runs each to a terminal status. The API process admits
Executions and never runs one. Implemented by `ExecutionHost`. One host has a
`host_id` and a generation (its image tag), recorded in `executor_hosts` and
on every container it creates (`syn.host_id`, `syn.host_generation`).
Specified in ADR-072.

An Executor is a host, not an Execution: nothing about an Execution's stream
says which Executor ran it.

## Run Queue

Where admitted Executions wait for an Executor: the `execution_runs` table,
behind the `ExecutionRunQueue` port. It is infrastructure state, written at
Admission, and never a projection, so a projection replay cannot hide admitted
work from Executors.

A run row moves `opening` -> `admitted` -> `claimed` -> `done`. Admission
writes `opening` before the Execution's stream exists and `admitted` after, so
a row stranded at `opening` is swept to `admitted` (stream present) or
`abandoned`, with reason `start not recorded` (stream confirmed absent; a failed
read leaves it `opening`). `abandoned` is provisional: a late successful open,
or a later sweep that finds the stream, promotes it to `admitted`. An expired
Lease goes `claimed` -> `fencing` -> `reaped` -> `interrupted` (see Fencing). A
resume whose inherited artifacts cannot yet be read is deferred back to
`admitted` with a `retry_at`. `RunCounts` is the number of rows in each state.

A run row is not an Execution and its states are not Execution statuses.

## Claim

An Executor taking one admitted Execution from the Run Queue to run, and the
`ClaimedRun` that results. Capacity and claim are one transaction: it locks the
execution budget row (`execution_budget`), counts the slots in use (`claimed`,
`fencing`, `reaped`) and, if one is free, takes the oldest claimable row. One
budget, held in that row, bounds every start path on every host, so two
generations can never enforce different numbers. Its value is measured from
memory per running Execution, never a constant.

An Executor claims only rows whose Event Epoch it can read, and never claims an
expired Lease to run it.

## Lease

How long a Claim stays valid without renewal: `leased_until`, plus a
`lease_token` bumped on every Claim and every Fencing. The holder renews every
TTL/3 (90 s TTL, 30 s renewal). A renewal whose token was superseded raises
`RunLeaseLost`, and the holder then cancels its own run.

A Lease is not a lock on the Execution. The token fences the Run Queue only:
a fenced holder's `renew` and `close` fail, but its event appends still succeed
until another writer advances the Execution's stream, whose expected-version
check is what then refuses them. The Lease is what says which Executor is alive
and holds the slot.

## Fencing

What happens to a Claim whose Lease expired: another Executor bumps the token
(`fencing`), removes the dead host's containers for that Execution (`reaped`),
then appends `WorkflowInterruptedEvent` and, as a separate later step, closes
the row and frees the slot (`interrupted`). A failed reap stays `fencing` and
is retried, so Fencing has no time bound once a Lease expires.
`fence_expired` returns each one as a `FencedRun`: the Execution and the host
that held it.

Fencing gives the row one **reconciler**, and only that host takes turns on it.
Another Executor replaces it (**takeover**) only once the reconciler has
**left**: its `executor_hosts` row is gone, by clean exit after a Drain, by a
restart in the same container, or by an operator **retiring** it after stopping
it. A stopped heartbeat is not leaving. A `host_id` is never reused.

An expired Lease is never claimed again to run. So an Execution runs at most
once: never a second workspace, never an automatic re-run, and no automatic
Resume after a host dies. An agent on a stalled host can still act until its
container is removed. That effect belongs to the one run (ADR-072 D5).

## Drain (of an executor)

An Executor stops claiming, finishes the Executions it holds, then exits.
Requested by setting `executor_hosts.draining`, which the host reads between
Claims. It is a property of the host: no Execution is signalled, paused or
moved, and admission stays open while it happens. Draining one generation
while the next is already claiming is how Executors upgrade without waiting.

**Not** the pit-stop drain, which closes admission and waits for the whole
platform to have no running Execution (see "Admission pause" under Pause).
"Drain" alone, in this context, means the Executor's.

## Event Epoch

The version of the orchestration events' shapes,
`ORCHESTRATION_EVENT_EPOCH`. Admission records the epoch it wrote with as a run
row's `writer_epoch`, and an Executor claims only rows whose `writer_epoch` is
no higher than its own. So an older Executor never loads events it cannot read:
newer work waits for a newer Executor. Every later append is held to the row's
`reader_epoch`, the least epoch of any host that may still load the stream (the
claimer and the reconciler); it rises only once the host holding it down has
left (ADR-072 D9). Changing an orchestration event's schema
without bumping the epoch fails a fitness test.

## Queued

An admitted Execution that no Executor has Claimed yet. Its status is
`running`: the aggregate is running from its start event, and waiting for a
slot is infrastructure state, not a domain decision. The read path shows it as
`queued: true`, derived from the Run Queue. `queued` is a flag, never one of an
Execution's statuses. (#1310 plan section 8, decision 2: Option A, decided
2026-10-05.)

Until ADR-072's admission ships, a start waiting on the in-process budget has
no stream at all, and #1574 reports it as a status of `queued` or `starting`.
That window disappears once Admission opens the stream itself (ADR-072 D12).

## Run-scoped to-do fold

The to-do list one Executor uses for the one Execution it is running: a fresh
`ExecutionTodoProjection` over a `RunTodoStore`, seeded from that Execution's
own events at Claim and discarded with the run. The shared `execution_todo`
projection feeds dashboards only. Nothing an Executor decides reads it.

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

The two meet at admission. An Execution launched into an Eval records the
Eval's Frozen Baseline as `eval_baseline` on its `WorkflowExecutionStarted`,
one `EvalBaselinePin` per repository: the Pin of the Baseline it was admitted
against, read from the Eval aggregate once it is Frozen (after a lost freeze
race, the winner's), never from a request or a read model. Empty for an Eval
with no repositories; absent for a run in no Eval.

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

## Default Eval

The Eval a Workflow's runs join when the launch names none: `default_eval_id`
in workflow YAML, or `PUT /workflows/{id}/default-eval`. Setting one requires
the Eval to exist and not be Archived; clearing one consults no Eval. A
reinstall replaces it with the package's, like every other template field.
Changing it never moves a run that has already started.

## Eval Selection

How a launch chose its Eval, recorded on `WorkflowExecutionStarted` as
`eval_selection` beside `eval_id`: `explicit` (the launch named one),
`workflow_default`, `ordinary` (see Ordinary Run), or `none` (no Eval named and
no Default Eval). Admission loads the Eval aggregate, never a read model, and
refuses a launch into an Eval that is missing or Archived before the
Execution starts.

## Ordinary Run

A launch that asks for no Eval (`--no-eval`, `no_eval: true`), even though its
Workflow has a Default Eval. It cannot also name an Eval.

## Attach

Put an Execution into an Eval after it was launched, in any status, including
terminal ones. It records `ExecutionAttachedToEval` on the Execution's stream,
never on the Eval's, and copies nothing from the Eval: the run keeps the state
it actually started from, and attaching does not Freeze the Eval. An Execution
belongs to at most one Eval. Attaching it to the Eval it already belongs to
succeeds and records nothing; attaching it to a different one is refused until
it is Detached.

Membership is decided before the Eval is consulted. A run already in the Eval
is a no-op success even after the Eval is Archived, so a repeated attach never
turns into a refusal. Only an attach that would record an event asks the Eval
aggregate whether it can take the run.

**Admission point.** An attach reads the Eval aggregate, then writes the
Execution's stream. The two are separate streams with no shared transaction,
and Attach deliberately does not write the Eval's (see Eval). So Archive closes
admission as of the Eval version the attach read: an `EvalArchived` that
commits after that read and before the Execution write does not refuse the
attach. The attach is ordered before the archive: it was decided and admitted
against the open Eval, and the run stays a member of the Archived Eval like any
run admitted earlier. Nothing marks it, and `attached_at` against `archived_at`
is not evidence either way, since the two clocks are stamped at decision time,
not commit time. Detach remedies it, and works on an Archived Eval. Every attach
that reads the Eval after the archive committed is refused. A launch is admitted
the same way.

## Detach

Take an Execution out of the Eval it belongs to. The command names that Eval,
so a stale caller cannot detach a run from an Eval it has since moved to.
Detaching consults no Eval, so it works on an Archived one. It never erases the
launch: `launched_eval_id` still records the Eval the run was launched into.

## Association Kind

How an Execution joined the Eval it belongs to now. `launched`: the launch
chose it. `attached`: it was Attached afterwards. A run Detached and then
Attached again, even to the same Eval, is `attached`, because the current
association was made after the fact.

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
- **Adopt / Reattach.** Reserved for #1310 Phase 3, no meaning assigned: a new
  process taking over a phase that is still running after the process that
  started it died. Not built, and deferred until an experiment shows it can be
  (ADR-072). Until then, an Executor that loses an Execution mid-phase Fences
  and interrupts it, and continuing it is a Resume.
- **Branch.** Reserved, no meaning assigned. If a chat-style "branch from here"
  operation is ever wanted, this is where it gets defined.
- **Retry.** A Phase attempt within one Execution (`PhaseRetryScheduled`), never
  a new Execution.
- **Fork, in the process sense.** `GRPC_ENABLE_FORK_SUPPORT` and `os.fork` are
  unrelated to this vocabulary. Renames must not touch them.
