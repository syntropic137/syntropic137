"""The probe must reproduce the finalizer's environment, not bypass it.

A fresh `docker exec` inherits the container's configured AGENTIC_SESSION_STORE_*
variables but NOT what init.sh exported into PID 1. The exporter reads neither -
it reads the translated SESSION_STORE_* names init.sh produces. Invoking the
binary directly therefore judged an exporter that had never been configured:

    {"error":"missing required env var SESSION_STORE_URL","store_url":null}

which parsed as FAILED, so every phase requested a backfill forever (#852).

Verified against the pinned omni image, through this exact command:

    captured_everything=true, uploaded=1, accepted=1
    origin.deployment = syntropic137__development
    the host-controlled probe state file was the one used
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from syn_adapters.workspace_backends.agentic.capture_probe import (
    CAPABILITY_PROVIDER_DIRS,
    EXIT_COMMAND_NOT_FOUND,
    EXIT_NO_CAPABILITY,
    EXPORTER_PROBE_COMMAND,
    PROBE_STATE_FILE,
    probe_capture,
)
from syn_adapters.workspace_backends.agentic.capture_result import CaptureExpectations
from syn_adapters.workspace_backends.agentic.capture_status import CaptureState
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    ExecutionResult,
)

if TYPE_CHECKING:
    from collections.abc import MutableMapping

SCRIPT = EXPORTER_PROBE_COMMAND[2]

EXPECTATIONS = CaptureExpectations(
    store_url="https://sessions.example.com",
    deployment="syntropic137__development",
    expect_sessions=True,
)


class TestTheProbeCommand:
    @pytest.mark.unit
    def test_it_runs_under_bash_not_sh(self) -> None:
        """/bin/sh in the workspace image is dash, and init.sh is bash-specific.

        Under dash it dies with `Syntax error: "(" unexpected` before exporting
        anything, and the probe then emits NO output and no verdict at all -
        the quietest possible failure. Found by running it, not by reading it.
        """
        assert EXPORTER_PROBE_COMMAND[0] == "bash"

    @pytest.mark.unit
    def test_it_sources_the_capability_before_running_the_exporter(self) -> None:
        assert SCRIPT.index('. "$init"') < SCRIPT.index("apss-session-exporter")

    @pytest.mark.unit
    def test_the_host_state_file_is_applied_after_the_source(self) -> None:
        """init.sh exports its OWN EXPORTER_STATE_FILE, into the agent-writable
        spool. Whichever assignment runs last wins, so ordering is the whole
        security property: an agent that can write the in-spool state file can
        fake `skipped_unchanged` and make a lost transcript read as captured.
        """
        assert SCRIPT.index('. "$init"') < SCRIPT.index("EXPORTER_STATE_FILE=")

    @pytest.mark.unit
    @pytest.mark.parametrize("provider_dir", CAPABILITY_PROVIDER_DIRS)
    def test_both_provider_names_are_tried(self, provider_dir: str) -> None:
        """`apss` is the current name; `seshmagic` is the legacy alias.

        The omni image running today has only `seshmagic`, so a probe that
        assumed the new name would report a capture failure on every phase of
        the only image in production.
        """
        assert provider_dir in SCRIPT

    @pytest.mark.unit
    def test_the_token_is_not_placed_on_the_command_line(self) -> None:
        """It arrives as the container's own AGENTIC_SESSION_STORE_AUTH.

        Passing it via `docker exec -e` would put the credential in the HOST
        process argv, readable by anyone who can list processes.
        """
        assert "AUTH" not in SCRIPT
        assert "TOKEN" not in SCRIPT


class TestMissingCapability:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_it_is_unknown_rather_than_disabled(self) -> None:
        """A store IS configured, so the transcripts were expected somewhere.

        DISABLED would close the case on sessions nobody has; CAPTURED would be
        a lie. UNKNOWN asks for the backfill and says why.
        """

        async def _no_capability(
            _command: list[str], *, timeout_seconds: int, environment=None
        ) -> ExecutionResult:
            return ExecutionResult(
                exit_code=EXIT_NO_CAPABILITY,
                success=False,
                duration_ms=1.0,
                stdout="",
            )

        outcome = await probe_capture(_no_capability, expectations=EXPECTATIONS)

        assert outcome.state is CaptureState.UNKNOWN
        assert outcome.needs_backfill
        assert "capability" in (outcome.reason or "")


class TestTheStateFileIsPassedUnderOurOwnName:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_the_probe_passes_syn_probe_state_file(self) -> None:
        """NOT EXPORTER_STATE_FILE: init.sh exports that one itself."""
        seen: MutableMapping[str, object] = {}

        async def _capture_env(
            _command: list[str], *, timeout_seconds: int, environment=None
        ) -> ExecutionResult:
            seen.update(environment or {})
            return ExecutionResult(exit_code=0, success=True, duration_ms=1.0, stdout="")

        await probe_capture(_capture_env, expectations=EXPECTATIONS)

        assert seen == {"SYN_PROBE_STATE_FILE": PROBE_STATE_FILE}


class TestAnImageThatDoesNoCaptureAtAll:
    """Verified against the pinned interactive-tmux image, which has NEITHER
    the capability directory nor the exporter binary:

        CAPABILITY ABSENT
        EXPORTER ABSENT
        wrapper exit = 127

    Before this wrapper, the probe ran the binary directly and got 127 from the
    shell, which reads as DISABLED. Letting a missing CAPABILITY alone decide
    would have made those images report UNKNOWN instead - requesting a backfill
    for transcripts that could never have existed. That is the same false alarm
    this change removes for the agentic backend, reintroduced for a different
    one, and it would have been my own regression.
    """

    @pytest.mark.unit
    def test_the_wrapper_re_raises_command_not_found(self) -> None:
        script = SCRIPT
        guard = script.index("command -v apss-session-exporter")
        assert guard < script.index(f"exit {EXIT_NO_CAPABILITY}")
        assert f"exit {EXIT_COMMAND_NOT_FOUND}" in script

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_no_exporter_is_disabled_not_unknown(self) -> None:
        """DISABLED does not request a backfill; UNKNOWN does."""

        async def _no_exporter(
            _command: list[str], *, timeout_seconds: int, environment=None
        ) -> ExecutionResult:
            return ExecutionResult(
                exit_code=EXIT_COMMAND_NOT_FOUND,
                success=False,
                duration_ms=1.0,
                stdout="",
            )

        outcome = await probe_capture(_no_exporter, expectations=EXPECTATIONS)

        assert outcome.state is CaptureState.DISABLED
        assert not outcome.needs_backfill
