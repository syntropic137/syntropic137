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
`interrupted`. The last four are terminal. `queued` is not one of them: it
describes a start that has no Execution yet (see Queued Start). There is no paused Execution - see
"Words we do not use".

## Phase

One step of a Workflow inside an Execution, with its own agent, model, prompt
and timeout. Phases run in a total order given by `order`, which
`WorkflowDefinition.from_yaml` guarantees is unique per Workflow.

A Phase is completed only when the Execution recorded it so. A Phase that
started and did not complete has no partial credit: there is no mid-phase
resume.

## Phase Deadline

When a Phase's agent is killed on its timeout (#1546). The clock starts when
the Phase's workspace is ready (`WorkspaceProvisionedForPhase`), not at
`PhaseStarted`, so the deadline is `provisioned_at` plus the effective timeout,
NOT the Phase's start plus it. The agent is told the same deadline as
`SYN_PHASE_DEADLINE`. Upstream-busy retries inside one run share it; a retried
Phase is provisioned again and gets a new one. It is derived, never recorded as
its own event: the facts it is made of are already events.

## Phase Cost Limit

The most a Phase may spend, in USD, before its agent is stopped (`max_cost_usd`,
#1376). The cost-axis twin of the timeout: a Phase fanning out to parallel
subagents turns a time bound into an unbounded cost. Spend is the per-turn
usage on the agent's own stream, priced by `price_tokens` (the same pricing the
execution's cost is built from), and one limit covers every attempt of the
Phase. Crossing it fails the Phase with `cost limit USD X exceeded at USD Y`: a
failure, not a cancel, so the Execution is resumable like one whose Phase hit
its deadline. Checked per turn, not reserved before each call, so turns already
in flight can land above it. Claude only: `codex exec` reports usage once, when
its run has ended, so a limit on a codex Phase could never stop it and is
refused at install. Not a separate budget from the
[Execution Budget](#execution-budget), which counts concurrent Executions, not
money.

## Quota Exhaustion

An upstream failure of kind `quota` (PC-83): the provider's usage allowance for
our account is spent until a reset it names ("try again at Oct 9th, 2026 9:10
PM"). Distinct from capacity, which returns in seconds: a quota returns on a
calendar date, so it is never retried, and the Phase fails with
`<provider> quota exhausted until <time>`. Recognised from codex's own fault
line only. **Unclear:** no real claude quota message exists in this repo or its
submodules, so claude quota text is not yet recognised and reads as `unknown`.

## Provision Step Timeout

A provisioning step that ran inside the workspace and did not finish before its
deadline (`ProvisionStepTimeoutError`, PC-126). The steps are named by
`ProvisionStep`: `secret_injection` (the ADR-024 setup script, including the
token mint and repository clones), `skill_install` (one `skills add`) and
`codex_sandbox_probe`. A timeout says the host was too loaded to answer, not that
the step is broken. So it is recorded as an upstream failure of kind
`unavailable`: transient, and the Execution is resumable. A skill install or a
sandbox probe is retried once in place. The setup script is not, because a clone
killed mid-transfer would be skipped by the re-run. Resuming provisions a fresh
workspace instead. Each deadline is a Setting.

## Fallback Agent

The agent (provider and model) a Phase declares under `fallback_agent`, to be
re-run on once when its own agent's upstream could not serve it: capacity that
outlived every retry, or a Quota Exhaustion (PC-83). The Phase's tools, budget
and sandbox bind the fallback too, so the provider rules that refuse an `agent`
refuse a `fallback_agent` at install. Acted on at execution (#1663): one
attempt, only when the primary's failed attempt got nowhere, drawn from the
same phase deadline as every attempt before it.

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

A Resume carries the skips before its Resume Phase forward as
`inherited_skipped_phase_ids`: a Skipped Phase is not a gap in the completed
prefix, so a Resume neither runs it nor counts it as work still to do (#1681).

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

## Declared Phase

A Phase an Execution set out to do, as its `WorkflowExecutionStarted` stated
it in `phase_definitions`. The same list `total_phases` counts. An Execution
started before those definitions were recorded (ISS-196) has none.

## Phase Plan

Every Declared Phase of an Execution, in order, each with where it stands:
the status it ran to here, `inherited`, `skipped`, or `pending`. Served on the
execution detail API as `phase_plan` (feedback cee46909). Not `phases`, which
holds only the Phases that started in this Execution.

## Pending Phase

A Declared Phase that has not started, is not an Inherited Phase and is not a
Skipped Phase: work still to come. Only ever a Phase Plan status; a Phase that
starts reports its own.

## Resume Phase

The Phase a resumed Execution starts at: the first Phase, in order, that the
original neither completed nor skipped. Restarted from its beginning.

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

## Quarantine Ref

Where a Phase's unpushed work is saved when the Phase ends without pushing it:
`refs/syn/lost/<execution>/<phase>`, outside every branch, fetched only on
purpose. A Quarantine Ref that LANDED is a fact on the Execution's stream: on
`WorkflowFailed` for a failure, and on `CancelledWorkQuarantined` for a
cancellation, which is recorded after the cancelled Phase's save has run
because `ExecutionCancelled` is written before it. Each carries a diffstat of
what the ref holds. The PR open from the Phase's branch is told once, by a
Quarantine Notice. (#1547.)

## Quarantine Notice

The one comment a PR gets naming the Quarantine Ref its run left behind, edited
rather than repeated when the Phase quarantines again. Owed until a PR exists
to receive it; with none yet, it is asked again on every live pass, and the
platform's clock tick guarantees a pass comes. (#1547.)

## Owed Cancelled Work

A cancelled Execution's landed Quarantine Refs that the event store refused to
take as `CancelledWorkQuarantined`, even after retries. They are kept in a
durable store, keyed by Execution and Phase, and the processor appends them at
the start of its next run. The row is removed after the event is on the
stream. A delete that fails leaves the row to be settled again. The aggregate
records a cancel's work once, so settling it twice still gives one fact.
(#1547.)

## Unrecorded Work

A cancel's landed Quarantine Refs that neither the event store nor the owed
store took. The cancelled result names them in `unrecorded_work`, so the cancel
is not reported as handled: the API turns that result into an execution failure
naming each ref and commit, never a cancelled summary. The processor holds them
in memory and its next run tries both stores again. A restart before then loses
that copy. The refs then survive only in that failure and the error log. (#1547.)

## Admission

The decision that an operation may proceed, recorded before any work begins.
Resuming is admitted or refused against the original's recorded state; the new
Execution is then created and started by a background processor.

An admitted Resume is not a started one. The two are separate facts, and a
successful API response reports the first.

## Execution Budget

How many Executions one API process runs at once (`SYN_EXECUTION_MAX_CONCURRENT`).
ONE budget bounds every start path: a direct start, a trigger dispatch and the
start of a resumed Execution all claim a slot from it. Sized against memory,
not isolation: each running Execution costs the API memory, and an API killed
for exceeding its limit takes every Execution it hosts with it. (#1557.)

## Queued Start

An admitted start waiting for an Execution Budget slot. It has an id and no
event stream yet, so `queued` is not one of an Execution's statuses: the API
reports `queued` (and `starting`, once it holds a slot and before its stream
opens) from the budget and the start's to-do record, with its position, in
place of a 404. First come, first served. A start already queued in a process
is never queued twice there; across processes, the Execution's first write is
what refuses a second start.

## Execution Request

The durable record that a direct start (`POST /workflows/{id}/execute`) was
admitted: `ExecutionRequested`, on its own `ExecutionRequest` stream, written
BEFORE the caller is told 200 and carrying everything the start needs. The
Execution it names does not exist yet. `ExecutionRequestStartProcessManager`
starts it from this record whenever no process already holds it - after a
restart, or when the route's own task never ran - so an accepted start is
never lost while it queues. Resume starts work the same way, from the
parent's `ExecutionResumed`; both use one start to-do list (#1557).

Its stream id is `request-<execution id>` (`execution_request_id`), never the
execution id itself. The event store keys a stream by aggregate id alone, not
by type and id, so a request at the execution's id would BE the execution's
stream, and the start's NoStream write would refuse the run as a duplicate.
That shipped once and stopped every direct start (v0.33.2-beta.8, beta.9).

## Withdraw

What cancelling a Queued Start does to its Execution Request (#1650):
`WithdrawExecutionRequest` -> `ExecutionRequestWithdrawn`, on the request's own
stream. A Queued Start has no Execution to cancel, so `cancel` on one withdraws
its request instead; on an Execution that exists, `cancel` is the Execution's
own and unchanged. Withdrawing twice records one withdrawal.

Withdraw decides about the request only. It does not know whether the
Execution started, and does not need to: both direct start paths read the
request again once they hold an Execution Budget slot, immediately before the
start, and a withdrawn one gives the slot straight back. A start already past
that read when the withdrawal lands still starts, and its own
`WorkflowExecutionStarted` outranks the withdrawal on the to-do list; that run
is cancelled as any other.

## Withdrawn

A request start to-do record's terminal status after `ExecutionRequestWithdrawn`.
Never offered again, and no later write walks it back to owed: it yields only
to `started`, as `failed` does. Rebuilt from the events alone on a restart, so a
withdrawn request is never started by a new process. The API reports a Queued
Start whose request is withdrawn as `cancelled`. Not an Execution status, for
the same reason `queued` is not: there is no Execution.

## Eval

An experiment: a Goal, measured by runs that all start from the same Repository
Baseline. Recorded as its own event stream, the Eval aggregate, identified by an
Eval id (`eval-` plus a uuid when the caller supplies none). Its name and tags
describe it and stay editable for its whole life. Its Goal and Baseline are what
it measures, and Freezing fixes them.

An Eval does not list its runs. An Execution records which Eval it belongs to,
so attaching a run is one write to the Execution and the Eval's stream does not
grow with every run. (Evals plan, #967.)

An Eval is long-lived: the same experiment is run again and again, under
different workflows and models, and every run adds a data point to the same
Eval. Its summary (run count, scored count, Pass Rate, last run and last
Verdict, Variants) is derived at read time and never stored on it.

## Run

An Execution that is a member of an Eval, seen from the Eval: one data point.
Membership is the Execution's (`eval_membership`), never the Eval's. A Run
carries what the dashboard compares: its Workflow, the models its phases
OBSERVED (the model that ran, as recorded on the session, never the alias a
phase declared - `opus` is not a model), its cost and duration, and its Score
if it has one. A Run's workflow version is the one it LAUNCHED from: the
template's installed package version, or its source digest when it has none,
written on the Execution's start event. Never the template's current version,
which is wrong for every Run that started before an update. A Run started
before this was recorded, or a resume, reports none rather than guess.

## Score

A judgement of one Run, recorded on the Eval: a Verdict, an optional number
from 0 to 1, Evidence (markdown: why), the scorer that produced it and its
version, and when. `RecordEvalRunScore` -> `EvalRunScored`. Only a member Run
can be scored (409 otherwise). Scoring is allowed on a Frozen or Archived Eval:
judging a run is not editing what the Eval measures. Re-scoring REPLACES the
Run's current Score; the earlier Scores stay in the Eval's events. Unlike
membership, Scores do grow the Eval's stream, one event per judgement.

## Verdict

`PASS`, `FAIL` or `ERROR` (`Verdict`, a StrEnum). `ERROR` means the Run could
not be judged (it did not finish, or produced nothing to judge): it counts as
scored, and is left out of the Pass Rate entirely: an unjudged Run is
neither a pass nor a fail. Not the same word as a Review Verdict, which is a
phase's own `certified` / `blocked` about a change; a scorer reads the Review
Verdict and records a Verdict about the Run.

## Pass Rate

`PASS` Runs divided by `PASS` + `FAIL` Runs. `ERROR` Runs are excluded, so a
provision failure never counts as a `FAIL`. None (shown as an em dash) when no
Run is judged `PASS` or `FAIL`: no data is not 0%.

## Variant

The Runs of one Eval that share a Workflow, the workflow version they launched
from, and the same sorted, unique set of observed models. Each Variant has its
own run count, pass count, Pass Rate, average cost (over Runs whose cost is
known) and last run. Two workflows under two models make four Variants of one
Eval; editing a workflow between Runs makes a fifth, because a different
version is a different treatment and pooling them would hide its effect. Runs
with no recorded version group together. Derived at read time from each Run's
execution detail (the observed models and cost are Lane 2 facts), never stored.

## Suite

A tag on Evals, not a record: `suite:<name>` plus `case:<case id>` names one
case's Eval, and that Eval is reused by every version of the suite and every
verifier (`scripts/eval_suite.py`). What differs between Runs goes on the Run
as tags: `suite-version:<n>` and `verifier:<workflow id>`.

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

A Workflow template is never archived while it has an active Execution. That is
decided from the template's own stream, not from a read model: every launch is
recorded there first (see Launch), so an archive and a launch racing each other
cannot both succeed (#1588).

## Launch

Starting an Execution of a Workflow template. Recorded on the TEMPLATE's stream
as `WorkflowTemplateExecutionLaunched`, before the Execution's own stream exists,
and refused if the template is Archived. A launch whose Execution stream never
appears stops counting as active after a grace period (`LAUNCH_GRACE`), so a
dispatch that died before starting cannot block an archive forever.

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

## Workspace Resource Usage

What one Phase's workspace consumed, measured once as it is torn down: CPU
time, CPU throttling, memory peak, OOM kills, the workspace's disk size, network
bytes, and the paths its delete could not remove (`WorkspaceUsage`). The
workspace provider measures it; the Phase that held the workspace records it,
as one `workspace_resource_usage` observation under that Phase's session.

It is telemetry (Lane 2), never domain state: no event, no aggregate, and a
failed measurement or write never fails a Phase. Each field is independently
unknown rather than zero when its read failed. A Phase retried after a failed
attempt held one workspace per attempt, so it has one usage per attempt. It
exists to size the platform against `docs/north-star.md`.

## Scripted Agent

What runs in a Phase's workspace in place of the agent CLI during a load test
(#1310): it replays a recorded session and performs the Phase's real side
effect without spending a token. It is production code with its own contract,
not a test double, which is why it is not called a stub, fake or mock. The
contract lives in `syn_perf.loadtest.scripted_agent_profile`:

- **Scripted Agent Profile** (`ScriptedAgentProfile`) - one load-test run's
  instructions, keyed by Phase id, sent to every workspace as the single
  `SYN_SCRIPTED_AGENT_PROFILE` environment variable. Read-only once validated.
- **Scripted Phase** (`ScriptedPhase`) - what the Scripted Agent does in one
  Phase: the stream it replays, the workload it burns, the side effect it
  performs and the artifact it writes.
- **Scripted Stream** (`ScriptedStream`) - the recorded session a Scripted
  Phase replays, its harness and CLI version, and the pacing.

The workspace image that carries a Scripted Agent is still called the stub
image in agentic-workspace; that names the image, not these models.

## Words we do not use

- **Suite** (as a record or an aggregate). A suite is a tag on Evals. There is
  no Suite stream, and a second aggregate for it was rejected (evals v2).

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
