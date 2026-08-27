# Delegated session capture (#895) and the delegation shim (#899)

**Status:** design, revision 3. Revised against a cross-model review that
declined to approve revision 1. Grounded in `exec-bf732cd21c0a` and
`exec-dd8d177bbde6` on the dev stack, 2026-08-27.

## What the owner needs

Fanning out sub-agents is about to become normal. Every delegated leg that
nothing records is unmeasured work: unattributed cost, unreadable reasoning,
nothing to learn from. The bar:

> For any delegated run, an operator or an agent can find what the delegate was
> asked, what it did, what it cost, and which parent it belonged to.

"For any" is the hard part, and it cannot be met by a mechanism the delegate
has to cooperate with. Two review passes converged on the same hole: a child
that bypasses the edge mechanism AND runs ephemerally leaves neither a
registered binding nor an exported transcript, so there is nothing for
reconciliation to find. Reconciliation closes binding-without-transcript and
transcript-without-binding. It cannot close neither.

So the design does two things rather than pretend otherwise:

1. **Moves the boundary to where bypass is deliberate.** The platform wrapper
   sits AT the canonical `claude` / `codex` command locations in the image, so
   invoking "the raw CLI" IS invoking the wrapper. Bypass then requires an
   absolute path to the real binary, which is an act rather than an accident.
2. **Names the residual instead of hiding it.** What remains uncovered is:
   a delegate launched by absolute path to the real binary, or by a mechanism
   that is neither the wrapper nor a native lifecycle event, AND run with
   persistence suppressed. That case is unobservable by any means short of
   process-level exec observation or a container supervisor, and this design
   does not claim to cover it.

The acceptance bar is therefore stated as: **any delegated run that goes
through the normal command path, or that persists a transcript, or that emits
a native lifecycle event, is attributable.** That is a weaker claim than "for
any delegated run" and it is the one the mechanism can actually support.

## What is measured, and what that does NOT prove

Run `exec-bf732cd21c0a`, claude leader delegating to codex:

| | Platform | Session-store export |
|---|---|---|
| Leader (claude/haiku) | 1 session, 63,296 tok, $0.0151 | `ecb7d14e` ClaudeCode |
| Delegated codex child | **none** | `01a04470` Codex, 5 msgs |

The child's exported record already carries `execution_id`, `workflow_id`,
`phase_id`, `workspace_id`.

**Store capture worked for both harness roots in this run.** That is the
correct, bounded claim. It is NOT an invariant, and revision 1 overstated it:

- an image whose recipe carries `--no-session-persistence` / `--ephemeral`
  makes a child unfindable, and the currently pinned omni digest still does;
- the existing capture invariant only proves a phase produced at least one
  transcript, which the leader alone satisfies;
- a SIGKILL can destroy the container-local spool before anything reconciles.

So: **lineage and guaranteed child completeness are the gaps.**

### Why lineage cannot be inferred

1. **Tags identify a WORKSPACE, not a lineage.** Every session in the
   container inherits them (`session_store_env.py:243`). They answer "which
   execution", never "who delegated to whom".
2. **Agent type is a heuristic about to break.** It worked here only because
   delegation is cross-harness today. Sub-agent fan-out is same-harness:
   identical tags, identical agent type, and concurrency defeats ordering.
3. **Two ID spaces.** Platform ids are minted by the processor; the store holds
   harness-native ids. The join must be established, not assumed.

## The protocol

One domain protocol, three discovery adapters, one importer. The protocol is
the contract; the adapters are how an edge gets reported; the importer is how
a linked session acquires content.

### 1. Binding protocol

```
DelegationStarted   delegation_attempt_id, parent_platform_session_id,
                    root_platform_session_id, provider, child_platform_session_id
DelegationBound     delegation_attempt_id, harness_session_id
DelegationFinished  delegation_attempt_id, exit_status
```

`delegation_attempt_id` is minted **by the edge adapter, before launch**, as a
ULID unique platform-wide. The SAME adapter that minted it emits
`DelegationBound` from that child's own stream, which is what makes the join
survive concurrent children of the same provider: the adapter holds the
attempt id and the stream in one scope, so nothing has to correlate by time or
order.

`DelegationStarted` and `DelegationBound` are separate because the child's
harness id does not exist until the child starts. Revision 1 asserted that id
might never be knowable; that was wrong. It is obtainable:

- **codex**: `codex exec --json` emits `thread.started.thread_id`, and the
  recipes already require `--json`.
- **claude**: the stream carries session identity in the same way the existing
  `EventStreamProcessor` already consumes.

A child that dies before emitting an id leaves its platform session visible as
`failed_before_capture` / `capture_missing`. **It must never silently vanish**,
because silently missing is exactly today's failure.

### 2. Three discovery adapters

| Delegation class | Edge comes from |
|---|---|
| Cross-harness shell (`codex exec`, `claude -p`) | `syn-delegate` shim |
| Native same-harness fan-out (Task/Agent) | Structured harness lifecycle events, already emitted as `subagent_started` / `subagent_stopped` (`EventStreamProcessor.py:605`, `ObservabilityCollector.py:189`) |
| Anything that reported no edge | Teardown reconciliation |

Revision 1 justified the shim using same-harness fan-out. That was backwards:
**native fan-out never invokes a shell shim.** It already has a structured
edge, which is cheaper and does not depend on an agent choosing to call
anything. The shim is for the cross-harness shell case specifically.

**But the existing native events are not sufficient on their own, and this is
net-new work rather than reuse.** `subagent_started` / `subagent_stopped`
carry a parent-side `tool_use_id` / `subagent_id` and NO `harness_session_id`
(`EventStreamProcessor.py:605`, `ObservabilityCollector.py:189`). They
establish an EDGE, not the platform-to-native BINDING, so concurrent native
children still cannot be joined to their exported transcripts. The native
adapter must obtain both the parent-side subagent identifier and the child's
transcript/session identifier; only the first exists today.

Note also that the third row is not a universal catch-all: reconciliation
recovers a run only if it persisted an export. A run that reported no edge and
persisted nothing is the residual named above.

The parent's platform id is already available in-container as
`CLAUDE_SESSION_ID` (`WorkspaceProvisionHandler.py:172`), for Claude phases and
delegation-enabled Codex phases though not every Codex container, since
`_build_agent_env` is conditional.

**Do not rename it.** Claude hooks and git hooks in agentic-primitives consume
that variable (for example `plugins/observability/hooks/handlers/observe.py`),
so a rename breaks them silently. Propagate both instead: keep
`CLAUDE_SESSION_ID` for existing correlation, and add `SYN_PARENT_SESSION_ID`
and `SYN_ROOT_SESSION_ID` as the provider-neutral delegation contract. Migrate
consumers deliberately before considering removal.

### 3. Reconciliation, because the shim is bypassable

An agent can call the raw CLI, an absolute path, a wrapper, or a native tool.
**Verifying that the deployed skill mentions `syn-delegate` proves guidance,
not execution.** Pattern-matching shell text is not an option: see
`syn_shared/delegation.py`, which documents why that gate was removed.

At teardown, reconcile every exported native session against registered
bindings:

- exported session with no binding -> **`unlinked_delegate`**, and create an
  orphan platform session rather than dropping it;
- registered child with no exported transcript -> **`capture_missing`**.

Neither mechanism is sufficient alone:

| Shim alone fails when | Reconciler alone fails when |
|---|---|
| it is bypassed | several same-harness children run concurrently |
| a native subagent never invokes it | it cannot tell leader from child from resumed session |
| it cannot bind the harness id | the child ran ephemerally and left nothing |
| it reports start then crashes before launch | stale pre-existing `$HOME` sessions enter the sweep |
| its control-plane call fails while the child runs | it has phase membership but no defensible parent edge |

Shim and native events give **intent and lineage**. Reconciliation gives
**completeness and recovery**. Both, or the bar is not met.

### 4. Delegated-session import processor

Creating a linked child aggregate does not give it a transcript, tokens, model
or cost. Today the leader is completed from processor-derived totals
(`SessionLifecycleManager.py:81`) and Lane 2 enrichment is keyed by platform
id, while the store is keyed by harness id.

An idempotent importer, built on the **Processor To-Do List** pattern this
codebase already mandates for long-running work rather than teardown-only
imperative code:

1. **start the child aggregate on `DelegationStarted`**, before any import.
   This is deliberately first: a child that fails before capture must still
   leave a visible platform session, which is impossible if the aggregate is
   only created once a transcript is found;
2. consume a confirmed platform/native binding;
3. read the provider-specific stored transcript;
4. emit Lane 2 token/tool/message observations under the CHILD platform id;
5. complete the child aggregate via commands;
6. price the child independently, since pricing is per session;
7. roll linked sessions into the execution total, subject to the
   double-counting rule below.

**The to-do list gives retryability, not idempotency.** Import identity must be
deterministic (derived from `delegation_attempt_id` plus the harness session
id, never from a generated id or a timestamp), and imported observations must
be deduplicated so a crash mid-import followed by a retry does not write a
second copy of the same tokens.

**Do not sum unconditionally.** Where a parent and child share a harness, the
parent's own reported totals may ALREADY include the delegated work, so adding
the child's tokens double-counts them. Whether totals overlap is
provider-specific and must be established per provider before any summing;
until it is established for a provider, the child's cost is attributed to the
child and NOT added to the execution total, because an undercount is
recoverable from the linked sessions and a silent double-count is not.

Emitting Lane 2 observations under the child platform id does not violate the
two-lane rule: the observations stay telemetry, and child lifecycle stays
aggregate commands.

**The two harnesses persist in different on-disk formats, and neither matches
its own stdout schema.** Existing stream processors will not work verbatim
against transcript files.

### 5. Root propagation is required, not derived

The aggregate sets `root = parent` when root is omitted
(`AgentSessionAggregate.py:139`). At depth 3 that is wrong:

```
A: parent=None, root=A
B: parent=A,    root omitted -> A   correct
C: parent=B,    root omitted -> B   WRONG, true root is A
```

Revision 1 said "root derivation is already written". That was misleading and
it was my sentence. Every child invocation must receive immutable recursive
context (`SYN_PARENT_SESSION_ID`, `SYN_ROOT_SESSION_ID`), and
`root_session_id` should be **required whenever `parent_session_id` is
present**. The silent fallback manufactures malformed deep trees.

**Enforce it at the COMMAND boundary only.** `SessionStartedEvent` keeps its
tolerant optional fields (`SessionStartedEvent.py:28`), which exist for
backward compatibility; applying the validator to historical event
deserialization would break replay. Production callers create only top-level
sessions today so none break, but one existing test deliberately constructs a
parent without a root and asserts the fallback
(`test_agent_session_aggregate.py:52`). That test encodes the old contract and
must be updated as a deliberate act, not discovered as a failure.

### 6. The read path is more than two fields

Both route response models omit lineage, and so does everything behind them:

- `syn_api.types.SessionSummary` (`types.py:469`) and `SessionDetail`
  (`types.py:786`) omit both fields;
- `list_sessions()` discards them when converting the domain read model
  (`sessions.py:345`);
- the projection supports a `parent_session_id` filter that the public list
  endpoint neither accepts nor forwards.

That list is still short. The HTTP contract has route-local models and
conversions of its own:

- `SessionSummaryResponse` and `SessionResponse` (`sessions.py:69`);
- the summary response builder (`sessions.py:565`);
- the detail response conversion (`sessions.py:710`);
- the dashboard's HAND-WRITTEN `SessionSummary` / `SessionResponse` TypeScript
  interfaces and query client (`types/index.ts:83`, `api/sessions.ts:9`), which
  codegen does not touch and which will silently drop the fields.

Thread both fields through every one of those, and route the lineage filter
projection query -> service -> FastAPI query parameter -> generated clients ->
whichever CLI or dashboard surface is meant to expose it.

## Acceptance

Not "a row exists". For a delegated run that went through the normal command
path, or persisted a transcript, or emitted a native lifecycle event:

- the child has its own platform session, linked to its parent, with a correct
  root at depth > 1;
- its tokens and cost are attributed to it, and roll into the execution total
  only where parent/child totals are known not to overlap for that provider;
- its transcript is reachable;
- a delegation that reported no edge but persisted a transcript surfaces as
  `unlinked_delegate`; one that registered but persisted nothing surfaces as
  `capture_missing`. Neither is silence.

**Explicitly out of scope**, and stated so it is a known limit rather than a
surprise: a delegate launched by absolute path to the real binary, bypassing
the wrapper, AND run with persistence suppressed. Nothing short of
process-level exec observation or a container supervisor sees that, and this
design does not claim to.

## Build order

Highest risk first, because each later step is cheap only if the earlier one
holds:

1. **The native fan-out binding.** It is the only part with no existing
   mechanism to extend: the events carry an edge but no harness session id.
   If this cannot be made to work per provider, the same-harness fan-out case
   the owner is heading into is not solvable this way, and it is better to
   learn that before building around it.
2. The wrapper at the canonical command paths, since the acceptance bar
   depends on it.
3. Binding protocol plus the cross-harness shim.
4. Import processor, with the double-counting question settled per provider.
5. Read path and lineage filters.

## Sequencing note

The codex->claude direction cannot be validated until an image carrying
agentic-primitives #376 is built and pinned. The pinned digest still bakes the
suppressing recipe, verified by reading it out of the digest rather than from
source.
