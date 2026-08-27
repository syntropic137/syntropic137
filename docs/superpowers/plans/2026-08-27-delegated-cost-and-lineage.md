# Delegated Cost and Lineage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A cross-harness delegated run (`codex exec` from a Claude phase, or the reverse) gets its own linked platform session, its tokens and cost attributed to it, and those costs added to the execution total.

**Architecture:** Split across two repositories along an existing boundary.
`agentic-primitives` owns everything harness-specific: how a CLI names its
sessions, what its stream and transcript look like, and the `syn-delegate`
binary that ships inside the workspace image. It already has this abstraction
(`harnesses/{claude,codex}`, `AgentName`, `HarnessTranscript`,
`TranscriptExtractionResult`), so this extends it rather than inventing one.
Syntropic137 owns what a delegation MEANS: the edge as a domain event, child
session aggregates, pricing, execution totals, and the read path.

The test for which side a change belongs on: **if it changes when Anthropic or
OpenAI ships a new CLI, it is agentic-primitives. If it changes when we decide
what a cost or a session is, it is Syntropic137.**

Contract-first, so the AP delivery lead time does not serialise the work. Task
0 defines the interface both sides code against; syn137 tasks proceed against a
test double while AP implements the real adapter.

**Tech Stack:** Python 3.14, Pydantic v2, event_sourcing SDK, TimescaleDB observability lane, pytest.

**Spec:** `docs/design/delegated-session-capture.md` (revision 3)

## Global Constraints

- pyright standard mode, no `Any` without justification; Pydantic models `frozen=True`, `extra="forbid"`.
- Aggregates decide state transitions; processors carry no business logic (AGENTS.md two-lane rule).
- Lane 2 observations are telemetry and are never replayed for state.
- No magic strings for domain values: use a `StrEnum` or shared constant.
- TODO/FIXME comments must reference a GitHub issue (`# TODO(#895): ...`).
- No em dashes in any file; plain hyphens.
- API routes must return Pydantic response models; run `just codegen` after any response-model change.
- **Cost rule, settled by measurement:** cross-harness delegates are separate processes with separate billing and MUST be added to execution totals. Native same-harness sub-agents already emit `token_usage` rows under the parent session and MUST NOT be added again.

---

## Repository split

| Lives in agentic-primitives | Lives in Syntropic137 |
|---|---|
| Native session id extraction per harness | `DelegationStarted/Bound/Finished` events |
| Transcript format parsing | Child session aggregate and lifecycle |
| The `syn-delegate` binary (ships in the image) | Pricing and execution totals |
| Delegation skills that call it | The read path and lineage queries |

**Delivery lead time is the cost of this split and must be planned around.**
Anything landing in AP needs merge -> image build -> release channel -> pin
bump in syn137 before it reaches a workspace. That is the chain #376 is
currently sitting in. Put as little in AP as genuinely needs to be there.

## Scope

**In:** cross-harness delegation only (`codex exec`, `claude -p` as a subprocess).

**Out, and tracked separately:**
- Native same-harness fan-out attribution (plan 2). Money is already counted; the missing piece is a sub-agent identifier on the `token_usage` observation.
- Read-path and query surface (plan 3).

---

### Task 0: The contract both repos code against (Syntropic137)

Defined first and deliberately tiny, so syn137 work is not blocked behind the
AP image chain. syn137 depends on this Protocol, never on a harness detail.

**Files:**
- Create: `packages/syn-domain/src/syn_domain/contexts/agent_sessions/domain/ports/delegate_identity.py`
- Test: `packages/syn-domain/tests/contexts/agent_sessions/test_delegate_identity_port.py`

**Interfaces:**
- Produces: `DelegateIdentity` Protocol with
  `native_session_id_from_stream(line: str) -> str | None`.

- [ ] **Step 1: Write the failing test**

```python
import pytest
from syn_domain.contexts.agent_sessions.domain.ports.delegate_identity import (
    DelegateIdentity,
)


class _FakeCodexIdentity:
    """Test double standing in for the agentic-primitives codex adapter."""

    def native_session_id_from_stream(self, line: str) -> str | None:
        if '"thread.started"' in line:
            import json

            return json.loads(line).get("thread_id")
        return None


@pytest.mark.unit
def test_double_satisfies_the_port() -> None:
    """syn137 codes against this Protocol so the AP image lead time does not
    serialise the domain work."""
    identity: DelegateIdentity = _FakeCodexIdentity()
    line = '{"type":"thread.started","thread_id":"01a04470-3a1c-7883"}'
    assert identity.native_session_id_from_stream(line) == "01a04470-3a1c-7883"
    assert identity.native_session_id_from_stream('{"type":"item.completed"}') is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/syn-domain/tests/contexts/agent_sessions/test_delegate_identity_port.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
"""Port for harness-native delegate identity.

WHY this is a port and not an implementation (issue #895): knowing that codex
emits `thread.started.thread_id` is knowledge about a CLI, not about our
domain. It changes when OpenAI ships a new codex version, so it belongs in
agentic-primitives beside the existing `harnesses/{claude,codex}` adapters.
Syntropic137 depends on this shape and never on the format behind it.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class DelegateIdentity(Protocol):
    """Recovers a harness's own session id from its output stream."""

    def native_session_id_from_stream(self, line: str) -> str | None:
        """The harness-native session id, or None if this line does not carry one."""
        ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/syn-domain/tests/contexts/agent_sessions/test_delegate_identity_port.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/syn-domain
git commit -m "feat(agent_sessions): port for harness-native delegate identity (#895)"
```

---

### Task 3A: Native session id extraction (agentic-primitives)

**Repo:** `AgentParadise/agentic-primitives`. Extends the EXISTING harness
abstraction rather than adding a parallel one.

**Files:**
- Modify: `lib/python/agentic_isolation/agentic_isolation/harnesses/codex/transcripts.py`
- Modify: `lib/python/agentic_isolation/agentic_isolation/harnesses/claude/`
- Test: `lib/python/agentic_isolation/tests/harnesses/test_native_session_id.py`

**Interfaces:**
- Produces: `native_session_id_from_stream(line: str) -> str | None` on each
  harness adapter, satisfying syn137's `DelegateIdentity` port from Task 0.

- [ ] **Step 1: Write the failing test**

```python
import pytest
from agentic_isolation.harnesses.codex import CodexHarness


@pytest.mark.unit
def test_codex_reports_its_thread_id() -> None:
    line = '{"type":"thread.started","thread_id":"01a04470-3a1c-7883"}'
    assert CodexHarness().native_session_id_from_stream(line) == "01a04470-3a1c-7883"


@pytest.mark.unit
def test_codex_ignores_other_event_types() -> None:
    """Mirrors the #792 finding already fixed in _resolve_session_id: reading
    an id off ANY line let an unrelated session's id through. Only the line
    type that actually carries identity is trusted."""
    assert CodexHarness().native_session_id_from_stream(
        '{"type":"item.completed","thread_id":"WRONG"}'
    ) is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest lib/python/agentic_isolation/tests/harnesses/test_native_session_id.py -v`
Expected: FAIL, method does not exist

- [ ] **Step 3: Implement on each adapter**

Reuse the existing constant naming the trusted line type; do not introduce a
second source of truth for which line carries identity.

- [ ] **Step 4: Run tests**

Expected: PASS

- [ ] **Step 5: Bump the plugin/package version and CHANGELOG**

AP CI fails a content change without a version bump, and without it
`claude plugin update` does not deliver the change.

- [ ] **Step 6: Commit and open a PR**

```bash
git commit -m "feat(harnesses): report the harness-native session id from a stream"
```

---

### Task 1: Domain events for the delegation edge

**Files:**
- Create: `packages/syn-domain/src/syn_domain/contexts/agent_sessions/domain/events/DelegationStartedEvent.py`
- Create: `packages/syn-domain/src/syn_domain/contexts/agent_sessions/domain/events/DelegationBoundEvent.py`
- Create: `packages/syn-domain/src/syn_domain/contexts/agent_sessions/domain/events/DelegationFinishedEvent.py`
- Test: `packages/syn-domain/tests/contexts/agent_sessions/test_delegation_events.py`

**Interfaces:**
- Produces: `DelegationStartedEvent(delegation_attempt_id, parent_session_id, root_session_id, child_session_id, provider)`, `DelegationBoundEvent(delegation_attempt_id, harness_session_id)`, `DelegationFinishedEvent(delegation_attempt_id, exit_status)`.

- [ ] **Step 1: Write the failing test**

```python
import pytest
from syn_domain.contexts.agent_sessions.domain.events.DelegationStartedEvent import (
    DelegationStartedEvent,
)


@pytest.mark.unit
def test_delegation_started_requires_root_when_parent_present() -> None:
    """Root is required, never derived. A silent root=parent fallback makes
    depth-3 trees wrong: C's root becomes B when the true root is A."""
    event = DelegationStartedEvent(
        delegation_attempt_id="01JB000000000000000000000A",
        parent_session_id="B",
        root_session_id="A",
        child_session_id="C",
        provider="codex",
    )
    assert event.root_session_id == "A"
    assert event.event_type == "DelegationStarted"


@pytest.mark.unit
def test_delegation_started_rejects_missing_root() -> None:
    with pytest.raises(ValueError):
        DelegationStartedEvent(
            delegation_attempt_id="01JB000000000000000000000A",
            parent_session_id="B",
            child_session_id="C",
            provider="codex",
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/syn-domain/tests/contexts/agent_sessions/test_delegation_events.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named '...DelegationStartedEvent'`

- [ ] **Step 3: Write minimal implementation**

```python
"""DelegationStarted event - a delegated child run was launched.

WHY root_session_id is required rather than derived (issue #895): the
aggregate's fallback sets root = parent when root is omitted, which is
correct only at depth 1. At depth 3 the child's root becomes its parent
rather than the true tree root, and nothing detects it.
"""

from __future__ import annotations

from event_sourcing import DomainEvent, event


@event("DelegationStarted", "v1")
class DelegationStartedEvent(DomainEvent):
    """A delegated child was launched by a parent session."""

    delegation_attempt_id: str
    """ULID minted by the edge adapter BEFORE launch, unique platform-wide."""

    parent_session_id: str
    root_session_id: str
    child_session_id: str
    provider: str
```

Then `DelegationBoundEvent(delegation_attempt_id: str, harness_session_id: str)` and
`DelegationFinishedEvent(delegation_attempt_id: str, exit_status: int)` in the same shape.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/syn-domain/tests/contexts/agent_sessions/test_delegation_events.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/syn-domain/src/syn_domain/contexts/agent_sessions/domain/events/ \
        packages/syn-domain/tests/contexts/agent_sessions/test_delegation_events.py
git commit -m "feat(agent_sessions): delegation edge events with required root (#895)"
```

---

### Task 2: Require root at the command boundary, keep the event tolerant

**Files:**
- Modify: `packages/syn-domain/src/syn_domain/contexts/agent_sessions/domain/commands/StartSessionCommand.py`
- Modify: `packages/syn-domain/tests/contexts/agent_sessions/domain/aggregate_session/test_agent_session_aggregate.py:52`
- Test: same file

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `StartSessionCommand` rejects `parent_session_id` without `root_session_id`.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.unit
def test_start_session_command_requires_root_with_parent() -> None:
    """Enforced at the COMMAND boundary only. SessionStartedEvent keeps its
    optional fields so historical replay does not break."""
    with pytest.raises(ValueError, match="root_session_id"):
        StartSessionCommand(
            aggregate_id="C",
            workflow_id="wf",
            phase_id="p",
            execution_id="e",
            agent_provider="claude",
            parent_session_id="B",
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/syn-domain/tests/contexts/agent_sessions/domain/aggregate_session/test_agent_session_aggregate.py -k requires_root -v`
Expected: FAIL, no exception raised

- [ ] **Step 3: Write minimal implementation**

```python
    @model_validator(mode="after")
    def _root_required_with_parent(self) -> StartSessionCommand:
        # WHY here and not on the event (issue #895): SessionStartedEvent's
        # lineage fields are optional for backward compatibility, and applying
        # this to event deserialisation would break replay of historical
        # streams written before delegation existed.
        if self.parent_session_id is not None and self.root_session_id is None:
            msg = "root_session_id is required when parent_session_id is set"
            raise ValueError(msg)
        return self
```

- [ ] **Step 4: Update the existing test that asserts the old fallback**

`test_agent_session_aggregate.py:52` constructs a parent without a root and
asserts `root == parent`. That encoded the old contract. Change it to pass an
explicit root, and add a sibling test asserting a raw `SessionStartedEvent`
with no root still rehydrates, proving replay is unaffected.

- [ ] **Step 5: Run the suite**

Run: `uv run pytest packages/syn-domain/tests/contexts/agent_sessions -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add packages/syn-domain
git commit -m "feat(agent_sessions): require root_session_id at the command boundary (#895)"
```

---

### Task 3: `syn-delegate` shim, provider-neutral env contract

**Files:**
- Create: `packages/syn-shared/src/syn_shared/delegate_shim.py`
- Modify: `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/WorkspaceProvisionHandler.py:172`
- Test: `packages/syn-shared/tests/test_delegate_shim.py`

**Interfaces:**
- Consumes: `DelegationStartedEvent`, `DelegationBoundEvent`, `DelegationFinishedEvent` from Task 1.
- Produces: `mint_attempt_id() -> str`. Consumes a `DelegateIdentity` (Task 0)
  for the native id; this module holds NO harness-specific parsing, because
  that lives in agentic-primitives (Task 3A).

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.unit
def test_parses_codex_thread_id_from_stream() -> None:
    """codex exec --json emits thread.started with the native id. Revision 1
    of the design assumed this id was unknowable; it is not."""
    line = '{"type":"thread.started","thread_id":"01a04470-3a1c-7883-9229-632918155605"}'
    assert (
        parse_harness_session_id("codex", line)
        == "01a04470-3a1c-7883-9229-632918155605"
    )


@pytest.mark.unit
def test_returns_none_for_unrelated_lines() -> None:
    assert parse_harness_session_id("codex", '{"type":"item.completed"}') is None


@pytest.mark.unit
def test_attempt_ids_are_unique() -> None:
    assert len({mint_attempt_id() for _ in range(1000)}) == 1000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/syn-shared/tests/test_delegate_shim.py -v`
Expected: FAIL with import error

- [ ] **Step 3: Write minimal implementation**

```python
def mint_attempt_id() -> str:
    """ULID minted by the edge adapter BEFORE launch.

    The SAME adapter emits DelegationBound from that child's own stream, so
    concurrent children of one provider never need correlating by time or
    order: the adapter holds the attempt id and the stream in one scope.
    """
    return str(ULID())


def parse_harness_session_id(provider: str, stream_line: str) -> str | None:
    """Extract the harness-native session id from a child's stream."""
    ...
```

Env contract, in `WorkspaceProvisionHandler`: **add** `SYN_PARENT_SESSION_ID`
and `SYN_ROOT_SESSION_ID`. Do NOT rename `CLAUDE_SESSION_ID`; Claude hooks and
git hooks in agentic-primitives read it (`plugins/observability/hooks/handlers/observe.py`)
and a rename breaks them silently.

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/syn-shared/tests/test_delegate_shim.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/syn-shared packages/syn-domain
git commit -m "feat(delegation): syn-delegate shim and provider-neutral env contract (#899)"
```

---

### Task 4: Import processor for the delegated child

**Files:**
- Create: `packages/syn-domain/src/syn_domain/contexts/agent_sessions/slices/import_delegated_session/ImportDelegatedSessionProcessor.py`
- Test: `packages/syn-domain/src/syn_domain/contexts/agent_sessions/slices/import_delegated_session/test_import_delegated_session.py`

**Interfaces:**
- Consumes: `DelegationBoundEvent` from Task 1.
- Produces: `ImportDelegatedSessionProcessor.handle_event()` (pure, writes to-dos) and `.process_pending()` (side effects, live only).

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.unit
@pytest.mark.asyncio
async def test_child_session_starts_before_import() -> None:
    """The child aggregate is created on DelegationStarted, BEFORE any
    transcript is read. A child that dies pre-capture must still leave a
    visible session; creating it only on successful import makes that
    impossible."""
    processor = ImportDelegatedSessionProcessor(repo, store, collector)
    await processor.handle_event(delegation_started_envelope)

    child = await repo.get_by_id("C")
    assert child is not None
    assert child.status is SessionStatus.RUNNING


@pytest.mark.unit
@pytest.mark.asyncio
async def test_import_is_idempotent_across_a_crash() -> None:
    """A to-do list gives retryability, not idempotency. Import identity is
    derived from (delegation_attempt_id, harness_session_id), never from a
    generated id or a timestamp, so a retry writes no second copy."""
    await processor.process_pending()
    first = collector.recorded_token_usage_count
    await processor.process_pending()
    assert collector.recorded_token_usage_count == first
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/syn-domain/src/syn_domain/contexts/agent_sessions/slices/import_delegated_session/ -v`
Expected: FAIL with import error

- [ ] **Step 3: Write minimal implementation**

Order matters and is not negotiable:
1. start the child aggregate on `DelegationStarted`;
2. consume the confirmed binding;
3. read the provider-specific transcript from the store;
4. emit Lane 2 observations under the CHILD platform session id;
5. complete the child aggregate;
6. price the child independently.

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/syn-domain/src/syn_domain/contexts/agent_sessions/slices/import_delegated_session/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/syn-domain
git commit -m "feat(agent_sessions): import delegated child sessions (#895)"
```

---

### Task 5: Add cross-harness children to execution totals, and only those

**Files:**
- Modify: `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execution_cost/timescale_query.py`
- Test: `packages/syn-domain/tests/contexts/orchestration/test_execution_cost_delegation.py`

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.unit
@pytest.mark.asyncio
async def test_cross_harness_child_is_added_to_the_execution_total() -> None:
    """A codex child of a claude phase is a separate process with separate
    billing. Nothing emits token_usage for it, so it is genuinely missing."""
    total = await query_execution_cost("exec-1")
    assert total.total_cost_usd == pytest.approx(LEADER_COST + CHILD_COST)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_native_subagent_is_not_added_twice() -> None:
    """A Claude session delegating to a Haiku subagent already emits
    token_usage rows for BOTH under the parent session. Adding an imported
    native child on top double-counts, which inflates exactly the fan-out
    the user runs to control spend."""
    total = await query_execution_cost("exec-2")
    assert total.total_cost_usd == pytest.approx(PARENT_TOTAL_INCLUDING_SUBAGENT)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest packages/syn-domain/tests/contexts/orchestration/test_execution_cost_delegation.py -v`
Expected: FAIL, child cost absent from the first, doubled in the second

- [ ] **Step 3: Implement**

Sum linked sessions whose `delegation_kind` is `CROSS_HARNESS`. Exclude
`NATIVE_SUBAGENT`. Use a `StrEnum`, not string literals.

- [ ] **Step 4: Run tests**

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/syn-domain
git commit -m "fix(costs): add cross-harness delegates to execution totals (#895)"
```

---

### Task 6: End-to-end proof against a real run

- [ ] **Step 1:** Rebuild the stack: `just dev-down && just dev`.
- [ ] **Step 2:** Run `syn workflow run claude-delegates-to-codex`.
- [ ] **Step 3:** Assert the execution has TWO platform sessions, the child's `parent_session_id` is the leader's id, and the total is the sum of both.
- [ ] **Step 4:** Confirm the delegate's cost is non-zero and matches the store transcript's tokens.
- [ ] **Step 5:** Commit the recorded fixture so this is a regression test, not a one-off.

---

### Task 7: Cost reconciliation, so the number is provable rather than asserted

Without this, "accurate cost" is a claim. This makes it something you can point
at, which is what an eval needs before it can be trusted.

**Files:**
- Create: `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execution_cost/reconcile.py`
- Test: `packages/syn-domain/tests/contexts/orchestration/test_cost_reconciliation.py`

**Interfaces:**
- Consumes: execution totals from Task 5.
- Produces: `reconcile_execution_cost(execution_id) -> CostReconciliation`
  with `tokens_match: bool`, `platform_cost_usd`, `harness_reported_cost_usd`,
  `divergence_usd`.

**Why two numbers exist.** The platform prices tokens from its OWN rate table.
Each harness also reports its own figure, captured today as
`total_cost_usd` off the CLI result event (`EventStreamProcessor.py:504`).
Those are independent, and they fail differently:

- **Tokens are objective.** The harness counts them and there is nothing to
  interpret. A mismatch is a bug, so it FAILS.
- **Dollars can legitimately diverge**, because the rate table is ours and has
  already drifted once (the gpt-5.6-sol correction), and because a codex
  session's cost is frozen at write time so a later rate fix reaches no
  completed session. So divergence is REPORTED, never silently reconciled.

Treating a dollar difference as a failure would train everyone to ignore it.
Treating it as a signal about the rate table is what makes it useful.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.unit
@pytest.mark.asyncio
async def test_token_mismatch_is_a_failure() -> None:
    """Tokens come from the harness. If ours disagree, we have a bug."""
    result = await reconcile_execution_cost("exec-token-mismatch")
    assert result.tokens_match is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cross_harness_child_tokens_are_included_in_the_match() -> None:
    """The delegate's tokens must be in the platform total, or reconciliation
    passes while the money is still missing, which is today's bug wearing a
    green check."""
    result = await reconcile_execution_cost("exec-with-codex-delegate")
    assert result.tokens_match is True
    assert result.platform_cost_usd > LEADER_ONLY_COST


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dollar_divergence_is_reported_not_failed() -> None:
    """A rate-table difference is a signal, not a defect. Failing on it would
    train people to ignore the check."""
    result = await reconcile_execution_cost("exec-rate-drift")
    assert result.tokens_match is True
    assert result.divergence_usd != 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest packages/syn-domain/tests/contexts/orchestration/test_cost_reconciliation.py -v`
Expected: FAIL with import error

- [ ] **Step 3: Implement**

Compare per session, not only in aggregate: a leader overcount and a child
undercount can cancel out and produce a total that looks correct.

- [ ] **Step 4: Run tests**

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/syn-domain
git commit -m "feat(costs): reconcile platform cost against harness-reported cost (#895)"
```

---

### Task 8: Regression fixtures from real runs

A recorded run is the only test that proves the whole chain, and it is what
stops this regressing silently later.

- [ ] **Step 1:** Record a real `claude-delegates-to-codex` run, capturing the
      leader stream, the child stream, and the exported transcripts.
- [ ] **Step 2:** Commit the recording as a fixture under
      `packages/syn-domain/tests/fixtures/delegation/`.
- [ ] **Step 3:** Write a replay test asserting: two platform sessions, the
      child's `parent_session_id` is the leader, correct `root_session_id`,
      the child's cost is non-zero, and the execution total is the sum.
- [ ] **Step 4:** Add the inverse fixture, a native sub-agent run, asserting
      the total is NOT the sum, because those tokens are already counted under
      the parent. **This is the double-count regression test and it is the one
      most likely to save you later**, since the bug it guards silently
      inflates rather than breaking anything visibly.
- [ ] **Step 5:** Verify both tests FAIL against the pre-change code, so they
      are known to be capable of failing rather than merely green.
- [ ] **Step 6: Commit**

```bash
git commit -m "test(delegation): regression fixtures for delegated cost (#895)"
```

## Self-review notes

- **Spec coverage:** contract (T0), harness identity in AP (T3A), binding protocol (T1, T3), required root (T2), importer with ordering and idempotency (T4), the summing rule (T5), e2e (T6), reconciliation (T7), regression fixtures (T8). Reconciliation, the wrapper-at-canonical-paths boundary, and the read path are deliberately NOT here; they are plans 2 and 3.
- **Known gap carried forward:** reconciliation for a bypassed delegate is not in this plan, so until plan 3 lands, a delegate that neither goes through the shim nor persists a transcript is still silent. That is the residual the design names.
