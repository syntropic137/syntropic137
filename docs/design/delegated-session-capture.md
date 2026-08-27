# Delegated session capture (#895) and the delegation shim (#899)

**Status:** design, revision 2. Revised against a cross-model review that
declined to approve revision 1. Grounded in `exec-bf732cd21c0a` and
`exec-dd8d177bbde6` on the dev stack, 2026-08-27.

## What the owner needs

Fanning out sub-agents is about to become normal. Every delegated leg that
nothing records is unmeasured work: unattributed cost, unreadable reasoning,
nothing to learn from. The bar:

> For any delegated run, an operator or an agent can find what the delegate was
> asked, what it did, what it cost, and which parent it belonged to.

"For any" is the hard part. A mechanism the delegate has to cooperate with
cannot meet it alone.

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

The parent's platform id is already available in-container as
`CLAUDE_SESSION_ID` (`WorkspaceProvisionHandler.py:172`). That name is
provider-specific and nesting will rely on it, so it should be renamed to a
provider-neutral contract (`SYN_PARENT_SESSION_ID`) before it is load-bearing.

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

1. consume a confirmed platform/native binding;
2. read the provider-specific stored transcript;
3. emit Lane 2 token/tool/message observations under the CHILD platform id;
4. start/complete the child aggregate via commands;
5. price the child independently, since pricing is per session;
6. make execution totals the sum of all linked sessions.

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

### 6. The read path is more than two fields

Both route response models omit lineage, and so does everything behind them:

- `syn_api.types.SessionSummary` (`types.py:469`) and `SessionDetail`
  (`types.py:786`) omit both fields;
- `list_sessions()` discards them when converting the domain read model
  (`sessions.py:345`);
- the projection supports a `parent_session_id` filter that the public list
  endpoint neither accepts nor forwards.

Thread both fields domain DTO -> API DTO -> summary/detail -> OpenAPI codegen,
and expose either lineage filters or a dedicated children/tree endpoint.

## Acceptance

Not "a row exists". For a delegated run:

- the child has its own platform session, linked to its parent, with a correct
  root at depth > 1;
- its tokens and cost are attributed to it and roll into the execution total;
- its transcript is reachable;
- a delegation that bypassed every edge mechanism still surfaces, as
  `unlinked_delegate` or `capture_missing`, never as silence.

## Sequencing note

The codex->claude direction cannot be validated until an image carrying
agentic-primitives #376 is built and pinned. The pinned digest still bakes the
suppressing recipe, verified by reading it out of the digest rather than from
source.
