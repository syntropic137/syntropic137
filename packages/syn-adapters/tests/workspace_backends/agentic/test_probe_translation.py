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
    EXIT_COMMAND_NOT_FOUND,
    EXIT_NO_CAPABILITY,
    EXPORTER_BIN,
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
    def test_it_names_the_exporter_by_absolute_path(self) -> None:
        """PATH resolution was forgeable.

        /opt/agentic is agent-owned in the workspace image, so the agent can
        replace the capability's init.sh and prepend a directory holding a fake
        exporter. Demonstrated against the pinned image: after replacing
        init.sh, `command -v apss-session-exporter` resolved to /tmp/evil and
        the probe returned captured_everything=true for a store it never
        contacted. The binary itself is root-owned 0755, so naming its path is
        what makes the audited program the one the host intended.
        """
        assert EXPORTER_BIN == "/usr/local/bin/apss-session-exporter"
        assert f"BIN={EXPORTER_BIN}" in SCRIPT
        assert 'exec "$BIN"' in SCRIPT

    @pytest.mark.unit
    def test_it_does_not_source_agent_writable_code(self) -> None:
        """An audit must not be configured by the party it audits.

        Sourcing init.sh handed the agent the audit's environment. The loud
        attack is a PATH prepend; the quiet one is SESSION_STORE_URL pointed at
        a sink the agent controls, where the REAL exporter uploads faithfully
        and returns a clean sweep for transcripts the store never saw.
        """
        assert "init.sh" not in SCRIPT
        assert ". " not in SCRIPT.replace("...", "")

    @pytest.mark.unit
    def test_it_translates_the_contract_itself(self) -> None:
        """Mirrors the seven exports the adapter performs, verified against the
        adapter in the pinned image. Duplication, deliberately: the alternative
        is trusting code the audited process can rewrite."""
        for produced in (
            "SESSION_STORE_URL",
            "SESSIONS_WRITE_TOKEN",
            "SESSION_STORE_TAGS",
            "SESSION_STORE_ORIGIN_DEPLOYMENT",
            "CLAUDE_PROJECTS_ROOT",
            "CODEX_SESSIONS_ROOT",
            "EXPORTER_STATE_FILE",
        ):
            assert produced in SCRIPT, f"{produced} is not translated"

    @pytest.mark.unit
    def test_the_deployment_is_carried_through(self) -> None:
        """Without it every workspace reports environment=container and the
        store cannot tell dev from production."""
        assert 'SESSION_STORE_ORIGIN_DEPLOYMENT="$AGENTIC_SESSION_STORE_DEPLOYMENT"' in SCRIPT

    @pytest.mark.unit
    def test_it_tells_the_exporter_to_ignore_state(self) -> None:
        """The state file is agent-writable, so its contents are not ours.

        Verified against the pinned image, twice in a row: run 1 and run 2 both
        reported skipped_unchanged=0, where a second sweep would normally
        report 1.
        """
        assert "--ignore-state" in SCRIPT

    @pytest.mark.unit
    def test_the_token_is_not_placed_on_the_command_line(self) -> None:
        """It is read from the container's own environment, so it never
        appears in the HOST's argv where anyone listing processes sees it."""
        assert 'SESSIONS_WRITE_TOKEN="$AGENTIC_SESSION_STORE_AUTH"' in SCRIPT
        assert "tok" not in SCRIPT


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
    """Verified against an image that has NEITHER the capability directory
    nor the exporter binary:

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
    def test_a_missing_binary_is_reported_before_anything_else(self) -> None:
        """127 first, so an image with no exporter reads as DISABLED.

        UNKNOWN would ask for a backfill of transcripts that could never have
        existed - such an image carries neither the capability nor the binary.
        """
        script = SCRIPT
        assert script.index(f"exit {EXIT_COMMAND_NOT_FOUND}") < script.index(
            f"exit {EXIT_NO_CAPABILITY}"
        )
        assert '[ -x "$BIN" ]' in script

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
