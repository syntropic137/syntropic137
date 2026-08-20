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

from syn_adapters.workspace_backends.service.setup_phase import (
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
        return self._results.pop(0) if self._results else _Result(0, "")


def _present() -> _Result:
    return _Result(0, "STAGED_CREDENTIAL_PRESENT\n")


def _absent() -> _Result:
    return _Result(0, "STAGED_CREDENTIAL_ABSENT\n")


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
        ws = _Workspace([_absent(), _Result(1, ""), _absent()])

        with pytest.raises(RuntimeError, match="unable to remove"):
            await _assert_codex_credential_removed(ws)

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
        """
        ws = _Workspace([_present(), _Result(0, ""), _Result(-1, "")])

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
        ws = _Workspace([_absent(), _Result(0, ""), _Result(0, output)])

        with pytest.raises(RuntimeError, match="unable to confirm removal"):
            await _assert_codex_credential_removed(ws)
