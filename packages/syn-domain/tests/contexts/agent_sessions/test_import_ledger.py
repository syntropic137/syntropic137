"""A delegate must be billed ONCE per execution, however often import runs.

#933 (re-import doubles) and #936 (a session billed in one phase, recounted in
the next) are the same defect seen twice: the platform session id is
uuid5(namespace, harness_session_id) with no execution or phase in it, so the
same harness session captured twice writes two cost-bearing summaries under ONE
platform id, and the cost queries SUM them.

These tests are written to FAIL against HEAD. They assert what was BILLED, not
how many calls were made: a recording fake shows one call per import and stays
green while the real append-only store holds two rows.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from decimal import Decimal

import pytest

from syn_adapters.import_ledger import InMemoryImportLedger
from syn_domain.contexts.agent_sessions import import_phase_delegates
from syn_domain.contexts.agent_sessions.delegate_import import DelegateImport
from syn_domain.contexts.agent_sessions.delegate_usage import StoredSession
from syn_domain.contexts.agent_sessions.import_ledger import BilledUsage

pytestmark = pytest.mark.unit

LEADER = "leader-1"
DELEGATE = "delegate-1"


def _claude(session_id: str, output: int, message_id: str) -> StoredSession:
    import json

    line = json.dumps(
        {
            "message": {
                "id": message_id,
                "model": "claude-sonnet-5",
                "usage": {
                    "input_tokens": 10,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                    "output_tokens": output,
                },
            }
        }
    )
    return StoredSession(session_id=session_id, source_format="claude-code-jsonl", raw=line)


@dataclass
class _Store:
    sessions: dict[str, StoredSession]

    async def fetch_session(self, session_id: str) -> StoredSession | None:
        return self.sessions.get(session_id)


@dataclass
class _AppendOnlyStore:
    """Stands in for agent_events: append-only, and the cost read SUMS.

    This is the whole point. A fake that records calls cannot express the
    defect, because the defect is that two rows both count.
    """

    rows: list[tuple[str, str, Decimal]] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    async def record_delegate_usage(
        self,
        *,
        session_id: str,
        usage: object,
        unpriced_reason: str | None,
        execution_id: str,
        phase_id: str,
        workspace_id: str | None,
    ) -> None:
        out = Decimal(str(getattr(usage, "output_tokens", 0) or 0))
        self.rows.append((session_id, execution_id, out))
        if unpriced_reason:
            self.reasons.append(unpriced_reason)

    def billed_output_for(self, execution_id: str) -> Decimal:
        """What the cost query would report: the SUM over rows."""
        return sum((o for _, e, o in self.rows if e == execution_id), Decimal("0"))

    def unpriced_reasons(self) -> list[str]:
        return self.reasons

    def cost_bearing_rows(self, execution_id: str) -> int:
        return sum(1 for _, e, o in self.rows if e == execution_id and o > 0)


async def _import(
    store: _Store,
    recorder: _AppendOnlyStore,
    *,
    phase: str,
    ledger: InMemoryImportLedger,
) -> None:
    await import_phase_delegates(
        store,
        recorder,
        leader_native_session_id=LEADER,
        captured_session_ids=[LEADER, DELEGATE],
        execution_id="exec-1",
        phase_id=phase,
        attempts_remaining=0,
        ledger=ledger,
    )


class TestTheSameDelegateIsBilledOncePerExecution:
    async def test_reimporting_one_phase_does_not_double_the_bill(self) -> None:
        """#933. A crash between the write and phase completion re-runs import."""
        store = _Store(
            {LEADER: _claude(LEADER, 100, "m-l"), DELEGATE: _claude(DELEGATE, 25, "m-d")}
        )
        recorder, ledger = _AppendOnlyStore(), InMemoryImportLedger()

        await _import(store, recorder, phase="phase-1", ledger=ledger)
        await _import(store, recorder, phase="phase-1", ledger=ledger)

        assert recorder.cost_bearing_rows("exec-1") == 1, (
            "a second import wrote a second cost-bearing row under the same "
            "session id; the cost query sums them"
        )
        assert recorder.billed_output_for("exec-1") == Decimal("25")

    async def test_a_session_billed_in_phase_one_is_not_rebilled_in_phase_two(self) -> None:
        """#936. The transcript is UNCHANGED, so the second phase owes nothing."""
        store = _Store(
            {LEADER: _claude(LEADER, 100, "m-l"), DELEGATE: _claude(DELEGATE, 25, "m-d")}
        )
        recorder, ledger = _AppendOnlyStore(), InMemoryImportLedger()

        await _import(store, recorder, phase="phase-1", ledger=ledger)
        await _import(store, recorder, phase="phase-2", ledger=ledger)

        assert recorder.billed_output_for("exec-1") == Decimal("25"), (
            "the same delegate was captured by two phases and billed twice"
        )

    async def test_a_grown_transcript_bills_only_the_delta(self) -> None:
        """The delegate really did more work; charge for that, not for all of it again."""
        store = _Store(
            {LEADER: _claude(LEADER, 100, "m-l"), DELEGATE: _claude(DELEGATE, 25, "m-d")}
        )
        recorder, ledger = _AppendOnlyStore(), InMemoryImportLedger()

        await _import(store, recorder, phase="phase-1", ledger=ledger)
        store.sessions[DELEGATE] = _claude(DELEGATE, 40, "m-d")
        await _import(store, recorder, phase="phase-2", ledger=ledger)

        assert recorder.billed_output_for("exec-1") == Decimal("40"), (
            "a grown cumulative transcript must total 40, not 25 + 40"
        )

    async def test_a_shrinking_transcript_is_refused_not_refunded(self) -> None:
        """A transcript cannot un-spend tokens.

        Smaller than what was billed means the store returned a different or
        truncated document. Charging a negative to reconcile would invent a
        refund, so the delta clamps at zero and the session is recorded as
        unpriced with the reason.
        """
        store = _Store(
            {LEADER: _claude(LEADER, 100, "m-l"), DELEGATE: _claude(DELEGATE, 40, "m-d")}
        )
        recorder, ledger = _AppendOnlyStore(), InMemoryImportLedger()

        await _import(store, recorder, phase="phase-1", ledger=ledger)
        store.sessions[DELEGATE] = _claude(DELEGATE, 25, "m-d")
        await _import(store, recorder, phase="phase-2", ledger=ledger)

        assert recorder.billed_output_for("exec-1") == Decimal("40"), (
            "a shrunken transcript must neither add nor subtract"
        )
        # The total alone does not distinguish "refused with a reason" from
        # "the refusal branch was deleted and the delta happened to be zero" -
        # a codex review pointed out this test passed either way. The unpriced
        # row IS the visible-undercount signal, so assert it exists.
        assert recorder.unpriced_reasons(), (
            "the shrink was silently ignored instead of recorded as unpriced; "
            "nothing downstream can tell this phase's cost is incomplete"
        )
        assert any("smaller than what was already billed" in r for r in recorder.unpriced_reasons())

    async def test_without_a_ledger_the_old_behaviour_is_unchanged(self) -> None:
        """The parameter is optional, so a caller that has not been wired yet
        keeps working - it simply keeps the double-count this fixes.

        Imports TWICE on purpose. Importing once would pass with every piece of
        deduplication deleted, which is the opposite of what this asserts.
        """
        store = _Store(
            {LEADER: _claude(LEADER, 100, "m-l"), DELEGATE: _claude(DELEGATE, 25, "m-d")}
        )
        recorder = _AppendOnlyStore()

        for phase in ("phase-1", "phase-2"):
            await import_phase_delegates(
                store,
                recorder,
                leader_native_session_id=LEADER,
                captured_session_ids=[LEADER, DELEGATE],
                execution_id="exec-1",
                phase_id=phase,
                attempts_remaining=0,
            )

        assert recorder.cost_bearing_rows("exec-1") == 2, (
            "without a ledger the delegate must still be billed twice - if this "
            "is 1, dedup is happening somewhere other than the ledger and the "
            "ledger tests are not testing what they claim"
        )


class TestConcurrentImportsDoNotBothBill:
    """Codex blocker 3: read-the-mark / write / raise-the-mark is check-then-act.

    Without exclusion spanning the whole window, two imports both read a mark
    of zero, both compute the same delta, and both append it. Monotonic writes
    do not save it - the duplicate charge is already recorded by then.
    """

    async def test_two_simultaneous_imports_of_one_session_bill_once(self) -> None:
        """The suspension point is DELIBERATE and the test is worthless without it.

        `InMemoryImportLedger` never awaits anything real, so two imports under
        `asyncio.gather` run start-to-finish one after the other and never
        interleave - the test then passes whether or not any exclusion exists.
        It did exactly that when first written, and removing the guard left it
        green. Yielding inside `already_billed` puts a real await between
        reading the mark and writing the charge, which is the window the race
        lives in.
        """

        class _SlowReadLedger(InMemoryImportLedger):
            async def already_billed(self, execution_id, harness_session_id):  # type: ignore[no-untyped-def]
                # Read FIRST, then yield. Yielding before the read lets the
                # second importer resume and see a mark the first one had
                # already committed - fresh data, no race, and the test passes
                # without exercising anything. Returning a value fetched
                # BEFORE the suspension is what makes it stale, which is the
                # actual shape of a concurrent read.
                mark = await super().already_billed(execution_id, harness_session_id)
                await asyncio.sleep(0)
                return mark

        store = _Store(
            {LEADER: _claude(LEADER, 100, "m-l"), DELEGATE: _claude(DELEGATE, 25, "m-d")}
        )
        recorder, ledger = _AppendOnlyStore(), _SlowReadLedger()

        await asyncio.gather(
            _import(store, recorder, phase="phase-1", ledger=ledger),
            _import(store, recorder, phase="phase-2", ledger=ledger),
        )

        assert recorder.billed_output_for("exec-1") == Decimal("25"), (
            f"the delegate was billed twice concurrently: {recorder.rows}"
        )

    async def test_the_guard_actually_excludes(self) -> None:
        """Prove the exclusion is real, not incidentally-serial test timing.

        A second entry while the first is inside must WAIT. Without this, the
        test above could pass simply because nothing yielded to the loop.
        """
        ledger = InMemoryImportLedger()
        order: list[str] = []

        async def hold(tag: str) -> None:
            async with ledger.guard("exec-1", DELEGATE):
                order.append(f"{tag}-in")
                await asyncio.sleep(0)
                order.append(f"{tag}-out")

        await asyncio.gather(hold("a"), hold("b"))

        assert order in (
            ["a-in", "a-out", "b-in", "b-out"],
            ["b-in", "b-out", "a-in", "a-out"],
        ), f"the two regions interleaved, so the guard does not exclude: {order}"

    async def test_different_sessions_are_not_serialized_against_each_other(self) -> None:
        """The lock is per session. A global one would serialize every import."""
        ledger = InMemoryImportLedger()
        inside = asyncio.Event()

        async def first() -> None:
            async with ledger.guard("exec-1", "session-a"):
                inside.set()
                await asyncio.sleep(0.05)

        async def second() -> None:
            await inside.wait()
            async with asyncio.timeout(0.02):
                async with ledger.guard("exec-1", "session-b"):
                    pass

        await asyncio.gather(first(), second())


class TestTheMarkOnlyRises:
    """Codex blocker 3, second half: an out-of-order commit must not lower it.

    A stale import carrying an older cumulative figure can land after a newer
    one committed. Writing it unconditionally would lower the mark, and the
    next read of the newer transcript would bill the difference a second time.
    """

    async def test_a_stale_commit_cannot_lower_the_mark(self) -> None:
        ledger = InMemoryImportLedger()

        await ledger.record_billed("exec-1", DELEGATE, BilledUsage(output_tokens=50))
        await ledger.record_billed("exec-1", DELEGATE, BilledUsage(output_tokens=40))

        mark = await ledger.already_billed("exec-1", DELEGATE)
        assert mark.output_tokens == 50, (
            "the stale figure lowered the mark; a reread of 50 would bill 10 again"
        )

    async def test_it_rises_per_bucket_not_per_row(self) -> None:
        """One bucket growing must not drag another backwards."""
        ledger = InMemoryImportLedger()

        await ledger.record_billed(
            "exec-1", DELEGATE, BilledUsage(output_tokens=50, cache_read_tokens=10)
        )
        await ledger.record_billed(
            "exec-1", DELEGATE, BilledUsage(output_tokens=20, cache_read_tokens=99)
        )

        mark = await ledger.already_billed("exec-1", DELEGATE)
        assert (mark.output_tokens, mark.cache_read_tokens) == (50, 99)


class TestTheLedgerIsGuardedAsInMemoryState:
    """ADR-060. Losing the mark on restart silently reverts to double-billing."""

    def test_constructing_it_outside_a_test_environment_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Patch the settings lookup rather than the environment.

        `uses_in_memory_stores` is `is_test or is_offline`, and under pytest
        `is_test` is unconditionally true - so no env var can express
        "production" from inside the suite. Setting SYN_ENV=production and
        asserting a raise would therefore fail for a reason that has nothing to
        do with the guard. Patching what the guard actually reads is the only
        way to exercise it.
        """
        import syn_adapters.in_memory as in_memory

        class _ProductionSettings:
            uses_in_memory_stores = False
            app_environment = "production"

        monkeypatch.setattr(in_memory, "get_settings", lambda: _ProductionSettings())

        with pytest.raises(in_memory.InMemoryAdapterError, match="test/offline only"):
            InMemoryImportLedger()

    def test_it_still_constructs_under_the_test_suite(self) -> None:
        """The negative control: without the patch it must work, or the test
        above would pass for the trivial reason that it never constructs."""
        assert InMemoryImportLedger() is not None


@dataclass
class _Capture:
    """Minimal stand-in for AuthoritativeCapture: only the ids are read."""

    agent_session_ids: tuple[str, ...] = (LEADER, DELEGATE)


class TestTheDeferredCrashWindowStaysNarrow:
    """#933's residual gap, deliberately left open - guarded so it cannot widen.

    Only the ordering test below guards the deferral itself. The retry-budget
    test guards a DIFFERENT hazard and is kept here because both are about
    cost silently going missing; its docstring explains the distinction.

    With the ledger wired, a second import no longer double-bills. What remains
    is a crash BETWEEN recording the charge and committing the mark: the retry
    reads a stale mark and bills again. No in-process mechanism closes that;
    it needs an idempotency key on the observation write, tracked in #933.

    Two things must stay true for the residual gap to remain merely an
    overcount rather than something worse, and neither is self-evident from
    reading the code - so they are asserted here.
    """

    async def test_the_charge_is_recorded_before_the_mark_advances(self) -> None:
        """Order is load-bearing, and the safe direction is counter-intuitive.

        write-then-mark: a crash in between re-bills on retry (#933, an
        OVERCOUNT - visible, and it looks like an expensive run).

        mark-then-write: a crash in between loses the charge forever (an
        UNDERCOUNT - silent, and nothing downstream can detect it, because a
        cost that was never recorded leaves no trace to reconcile against).

        Reversing these looks like a harmless refactor and is not, so pin it.
        """
        events: list[str] = []

        class _OrderRecordingLedger(InMemoryImportLedger):
            async def record_billed(self, execution_id, harness_session_id, billed):  # type: ignore[no-untyped-def]
                events.append("mark")
                await super().record_billed(execution_id, harness_session_id, billed)

        class _OrderRecordingStore(_AppendOnlyStore):
            async def record_delegate_usage(self, **kwargs: object) -> None:
                events.append("charge")
                await super().record_delegate_usage(**kwargs)  # type: ignore[arg-type]

        store = _Store(
            {LEADER: _claude(LEADER, 100, "m-l"), DELEGATE: _claude(DELEGATE, 25, "m-d")}
        )
        await _import(
            store, _OrderRecordingStore(), phase="phase-1", ledger=_OrderRecordingLedger()
        )

        assert events.index("charge") < events.index("mark"), (
            "the mark advanced before the charge was recorded; a crash between "
            "them now loses the charge silently instead of overcounting it"
        )

    async def test_the_import_has_no_retry_budget(self) -> None:
        """Raising this budget would silently DROP delegate cost.

        A codex review corrected the original justification for this test,
        which claimed it protected #933's charge/mark crash window. It does
        not: `attempts_remaining` only decides whether an unreadable session is
        held back into `retry_ids` instead of being written
        (delegate_import.py), and this caller performs no retry at all.

        The test still earns its place, for a different and worse reason.
        NOTHING in orchestration consumes `retry_ids`. So a budget above zero
        means retryable sessions are held back for a retry that never comes,
        and their cost is never written by anyone - a silent undercount, with
        no unpriced row to reveal it. Zero is what forces those sessions to be
        written as visible gaps instead.

        If a real retry mechanism is added, this test SHOULD fail; that is the
        point at which someone has to decide what consumes `retry_ids`.
        """
        seen: list[int] = []

        async def _spy(*_args: object, **kwargs: object) -> object:
            seen.append(int(kwargs["attempts_remaining"]))  # type: ignore[call-overload]
            return DelegateImport(imported=(), retry_ids=(), attempts_remaining=0)

        import syn_domain.contexts.orchestration.slices.execute_workflow.phase_delegate_import as pdi

        original = pdi.import_phase_delegates
        pdi.import_phase_delegates = _spy  # type: ignore[assignment]
        try:
            await pdi.import_delegates_for_phase(
                _Capture(),
                session_store=object(),
                writer=object(),
                leader_native_session_id=LEADER,
                phase_id="phase-1",
                execution_id="exec-1",
                workspace_id=None,
            )
        finally:
            pdi.import_phase_delegates = original  # type: ignore[assignment]

        assert seen == [0], f"the import gained a retry budget: {seen}"


class TestAFailedImportKeepsTheLeaderIdentity:
    """A codex review found the first fix for this was INEFFECTIVE.

    Moving the pop after the import looked right, but
    `import_delegates_for_phase` catches the exception and returns normally, so
    the caller could not tell success from failure and popped either way. The
    identity was still gone, the retry still could not tell the leader from its
    delegates, and the phase's delegate cost was still dropped.
    """

    async def _run(self, *, blow_up: bool) -> dict[tuple[str, str], str]:
        import syn_domain.contexts.orchestration.slices.execute_workflow.phase_delegate_import as pdi

        class _Workspace:
            execution_id = "exec-1"
            workspace_id = "ws-1"

        class _Capture:
            agent_session_ids = (LEADER, DELEGATE)

        async def _capture_phase(*_a: object, **_k: object) -> object:
            return _Capture()

        async def _boom(*_a: object, **_k: object) -> object:
            raise RuntimeError("store unreachable")

        async def _ok(*_a: object, **_k: object) -> object:
            return DelegateImport(imported=(), retry_ids=(), attempts_remaining=0)

        leader_ids = {("exec-1", "phase-1"): LEADER}
        orig_capture, orig_import = pdi.capture_phase_session, pdi.import_phase_delegates
        pdi.capture_phase_session = _capture_phase  # type: ignore[assignment]
        pdi.import_phase_delegates = _boom if blow_up else _ok  # type: ignore[assignment]
        try:
            await pdi.capture_and_import_phase(
                object(),
                _Workspace(),
                session_store=object(),
                writer=object(),
                leader_native_ids=leader_ids,
                session_id="sess-1",
                phase_id="phase-1",
            )
        finally:
            pdi.capture_phase_session = orig_capture  # type: ignore[assignment]
            pdi.import_phase_delegates = orig_import  # type: ignore[assignment]
        return leader_ids

    async def test_a_failed_import_leaves_the_leader_for_the_retry(self) -> None:
        remaining = await self._run(blow_up=True)
        assert ("exec-1", "phase-1") in remaining, (
            "the leader identity was consumed by a failed import; the retry now "
            "cannot tell the leader from its delegates and will refuse"
        )

    async def test_a_successful_import_still_releases_it(self) -> None:
        """The negative control. Without this the fix could degenerate into
        'never release', and a later run of the same phase id would pick up a
        stale leader."""
        remaining = await self._run(blow_up=False)
        assert ("exec-1", "phase-1") not in remaining
