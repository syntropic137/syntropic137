"""The staged-credential guard must fail CLOSED, including when it cannot look.

Two independent defects made it inert:

1. `" ".join(argv)` reassociated `["sh","-c","test -e X"]` into
   `sh -c test -e X`, running `test` with no operands, which always exits 1.
   The guard read that as "credential gone" on every run.
2. Even with quoting fixed, `exit_code != 0` still conflated ABSENT with every
   way of failing to look - timeout, provider error, missing workspace. And the
   recheck raised only on exit 0, so a FAILED recheck was accepted as proof of
   removal.

Absence and inability to verify absence now travel on different channels.
"""

from __future__ import annotations

import pytest

from syn_adapters.workspace_backends.service import setup_phase
from syn_adapters.workspace_backends.service.setup_phase import (
    _MAX_ATTEMPTS,
    _RETRY_BACKOFF_SECONDS,
    _assert_codex_credential_removed,
    _CredentialState,
    _staged_credential_state,
)


class _Result:
    def __init__(self, exit_code: int = 0, stdout: str = "") -> None:
        self.exit_code = exit_code
        self.success = exit_code == 0
        self.stdout = stdout
        self.stderr = ""
        self.duration_ms = 1.0
        self.timed_out = False


class _Workspace:
    workspace_id = "ws-1"

    def __init__(self, results: list[_Result]) -> None:
        self._results = list(results)
        self.calls: list[list[str]] = []

    async def execute(self, command: list[str], **_kw: object) -> _Result:
        self.calls.append(command)
        if not self._results:
            # Was an endless supply of `_Result(0, "")`. Once the guard retries,
            # a test that under-declares its sequence is silently topped up with
            # invented answers and passes on them - so running out is the test's
            # bug, and says so.
            raise AssertionError(f"unscripted execute #{len(self.calls)}: {command}")
        return self._results.pop(0)


def _probes(calls: list[list[str]]) -> list[list[str]]:
    return [c for c in calls if c[0] == "sh"]


def _removals(calls: list[list[str]]) -> list[list[str]]:
    return [c for c in calls if c[0] == "rm"]


def _present() -> _Result:
    return _Result(0, "STAGED_CREDENTIAL_PRESENT\n")


def _absent() -> _Result:
    return _Result(0, "STAGED_CREDENTIAL_ABSENT\n")


def _stalled() -> _Result:
    """A probe that did not answer: the provider's own failure code, no output.

    This is what a momentary stall looks like at this call site, and what
    #1293 counted as a confirmed failure.
    """
    return _Result(-1, "")


def _removal_ok() -> _Result:
    return _Result(0, "")


class TestTheProbeDistinguishesAbsentFromUnverifiable:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_absent_is_reported_from_output(self) -> None:
        state = await _staged_credential_state(_Workspace([_absent()]))
        assert state is _CredentialState.ABSENT

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_present_is_reported_from_output(self) -> None:
        state = await _staged_credential_state(_Workspace([_present()]))
        assert state is _CredentialState.PRESENT

    @pytest.mark.unit
    @pytest.mark.asyncio
    @pytest.mark.parametrize("exit_code", [1, -1, 137])
    async def test_a_failed_probe_is_unverifiable_not_absent(self, exit_code: int) -> None:
        """-1 is the provider's own failure code, and 1 was the old false 'gone'."""
        state = await _staged_credential_state(_Workspace([_Result(exit_code, "")]))
        assert state is _CredentialState.UNVERIFIABLE

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_unrecognised_output_is_unverifiable(self) -> None:
        """A zero exit with output we cannot read is not an answer."""
        state = await _staged_credential_state(_Workspace([_Result(0, "wat")]))
        assert state is _CredentialState.UNVERIFIABLE


class TestTheGuardFailsClosed:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_removal_runs_even_when_the_probe_says_absent(self) -> None:
        """ABSENT from the probe is not proof.

        `[ -e PATH ]` is false both when the path is gone and when it cannot be
        inspected - an untraversable parent answers "no" indistinguishably.
        The removal is what separates those, so it runs unconditionally.
        """
        ws = _Workspace([_absent(), _Result(0, ""), _absent()])

        await _assert_codex_credential_removed(ws)

        assert any(call[0] == "rm" for call in ws.calls)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_a_present_credential_is_removed_then_confirmed(self) -> None:
        ws = _Workspace([_present(), _Result(0, ""), _absent()])

        await _assert_codex_credential_removed(ws)

        # probe, rm, re-probe
        assert len(ws.calls) == 3
        assert ws.calls[1][:3] == ["rm", "-f", "--"]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_a_failed_removal_raises(self) -> None:
        """The exit status of `rm -f` is the authority.

        It returns 0 for a path already gone, and nonzero only when it could
        not act - permission denied, an untraversable parent - which is exactly
        the case the probe misreports as absent. Previously unchecked.
        """
        ws = _Workspace([_absent(), *[_Result(1, "")] * _MAX_ATTEMPTS])

        with pytest.raises(RuntimeError, match="unable to remove") as raised:
            await _assert_codex_credential_removed(ws)

        # Every attempt failed, so the verdict is unchanged - the retry buys
        # the stalling container a second look, not a different answer.
        assert len(_removals(ws.calls)) == _MAX_ATTEMPTS
        assert f"attempts={_MAX_ATTEMPTS}" in str(raised.value)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_a_credential_that_survives_removal_raises(self) -> None:
        ws = _Workspace([_present(), _Result(0, ""), _present()])

        with pytest.raises(RuntimeError, match="unable to confirm removal"):
            await _assert_codex_credential_removed(ws)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_an_unverifiable_recheck_raises(self) -> None:
        """The defect this class exists for.

        A recheck that timed out has NOT shown the credential is gone.
        Accepting it is the same fail-open the guard was written to prevent.
        Retrying it (#1293) does not change that: silence is still not
        clearance once the bounded budget is spent.
        """
        ws = _Workspace([_present(), _removal_ok(), *[_stalled()] * _MAX_ATTEMPTS])

        with pytest.raises(RuntimeError, match="unable to confirm removal"):
            await _assert_codex_credential_removed(ws)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_an_unverifiable_first_probe_does_not_return_early(self) -> None:
        """It must attempt removal rather than assume nothing is there."""
        ws = _Workspace([_Result(-1, ""), _Result(0, ""), _absent()])

        await _assert_codex_credential_removed(ws)

        assert any(call[0] == "rm" for call in ws.calls)

    @pytest.mark.unit
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "output",
        ["NOT_STAGED_CREDENTIAL_ABSENT", "STAGED_CREDENTIAL_ABSENT_MAYBE", "x ABSENT"],
    )
    async def test_lookalike_output_is_not_accepted_as_absent(self, output: str) -> None:
        """The match is exact on the final line, not a suffix.

        `endswith` would have accepted "NOT_STAGED_CREDENTIAL_ABSENT", which
        contradicts the rule that output we cannot recognise is UNVERIFIABLE.
        """
        ws = _Workspace([_absent(), _removal_ok(), *[_Result(0, output)] * _MAX_ATTEMPTS])

        with pytest.raises(RuntimeError, match="unable to confirm removal"):
            await _assert_codex_credential_removed(ws)


class TestATransientStallDoesNotDiscardTheRun:
    """#1293. Failing closed was right; deciding it on one 5s exec was not.

    A probe that did not answer established NOTHING - not that the credential
    is there, not that it is gone. It was counted as a confirmed failure, and
    one momentary stall threw away an execution mid-run (exec-b8221f1169d9,
    $3.70 at phase 1 of 3; the identical retry completed). The verdict is
    unchanged - what is retried is the absence of an answer.
    """

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_a_stalled_recheck_that_then_answers_absent_completes(self) -> None:
        """The exact incident: recheck #1 does not answer, recheck #2 says gone."""
        ws = _Workspace([_absent(), _removal_ok(), _stalled(), _absent()])

        await _assert_codex_credential_removed(ws)

        assert len(_probes(ws.calls)) == 3  # advisory + two rechecks

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_a_stalled_removal_that_then_succeeds_completes(self) -> None:
        """The same defect one exec earlier, and `rm -f` is idempotent.

        A stalled removal raised "unable to remove" and discarded the run just
        as finally. Retrying cannot excuse a removal that is genuinely refused
        - see the failed-removal test, where all four attempts fail and it
        still raises.
        """
        ws = _Workspace([_absent(), _Result(1, ""), _removal_ok(), _absent()])

        await _assert_codex_credential_removed(ws)

        assert len(_removals(ws.calls)) == 2

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_a_present_recheck_fails_at_once_and_is_never_retried(self) -> None:
        """The line the retry must not cross.

        PRESENT is an ANSWER: the credential survived a removal that reported
        success. Probing again until some attempt says ABSENT would retry a
        real finding into a pass. It fails on the first one, and the workspace
        double has no further answers to give - asking for one is the failure.
        """
        ws = _Workspace([_absent(), _removal_ok(), _present()])

        with pytest.raises(RuntimeError, match="unable to confirm removal") as raised:
            await _assert_codex_credential_removed(ws)

        assert len(_probes(ws.calls)) == 2  # advisory + ONE recheck
        assert "attempts=1" in str(raised.value)
        assert "#1 present" in str(raised.value)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_the_budget_is_bounded_and_the_error_names_every_attempt(self) -> None:
        """Fatal is not the problem; undiagnosable is.

        "unable to confirm removal" alone ended a run without saying whether
        the credential was seen, or how many times anything was tried.
        """
        ws = _Workspace([_absent(), _removal_ok(), *[_stalled()] * _MAX_ATTEMPTS])

        with pytest.raises(RuntimeError, match="unable to confirm removal") as raised:
            await _assert_codex_credential_removed(ws)

        assert len(_probes(ws.calls)) == _MAX_ATTEMPTS + 1
        message = str(raised.value)
        assert f"attempts={_MAX_ATTEMPTS}" in message
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            assert f"#{attempt} unverifiable" in message

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_the_retries_back_off_and_stop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Hammering a stalled container at once is how you keep it stalled."""
        slept: list[float] = []

        async def _record(seconds: float) -> None:
            slept.append(seconds)

        monkeypatch.setattr(setup_phase.asyncio, "sleep", _record)
        ws = _Workspace([_absent(), _removal_ok(), *[_stalled()] * _MAX_ATTEMPTS])

        with pytest.raises(RuntimeError, match="unable to confirm removal"):
            await _assert_codex_credential_removed(ws)

        # Waits go BETWEEN attempts, so the last one is not followed by one.
        assert slept == list(_RETRY_BACKOFF_SECONDS)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_recovering_early_stops_waiting(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A run that recovers pays one backoff, not the whole schedule."""
        slept: list[float] = []

        async def _record(seconds: float) -> None:
            slept.append(seconds)

        monkeypatch.setattr(setup_phase.asyncio, "sleep", _record)
        ws = _Workspace([_absent(), _removal_ok(), _stalled(), _absent()])

        await _assert_codex_credential_removed(ws)

        assert slept == [_RETRY_BACKOFF_SECONDS[0]]
