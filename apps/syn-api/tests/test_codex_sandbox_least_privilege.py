"""A codex phase must not receive more authority than it declared (#1157, #1161).

Every codex phase used to be built with ``--sandbox danger-full-access``
regardless of what its workflow said. On ``exec-dff4ff410bb1`` a verify phase
used that grant to merge, commit and push the change it then certified, and
the resulting verdict was indistinguishable from a real one.

The levels were measured against codex 0.147.0 rather than assumed:

    workspace-write   write: yes   git commit: yes   network: yes
    read-only         write: no    git commit: no    network: yes

Network egress survives every level, so ``read-only`` is the only setting that
stops a verifier from producing commits, and it stops it at ``git commit``
(``fatal: Unable to create '.git/index.lock'``) rather than at the push.
"""

from __future__ import annotations

import pytest

from syn_api._wiring import _build_codex_command, _resolve_sandbox
from syn_shared.agents import (
    CODEX_SANDBOX_FLAGS,
    DEFAULT_PHASE_SANDBOX,
    PhaseSandbox,
    UnsupportedPhaseSandboxError,
)

pytestmark = pytest.mark.unit


def _sandbox_arg(argv: list[str]) -> str:
    return argv[argv.index("--sandbox") + 1]


class TestDefaultIsLeastPrivilege:
    def test_undeclared_phase_keeps_todays_behaviour(self) -> None:
        """The default is full access, and that is a stopgap, not a target.

        Both lower levels were tried and are unusable until #1167 lands:
        ``WORKSPACE_WRITE`` broke every codex phase in v0.28.0-beta.5 (the
        deliverable write under ``artifacts/output/`` was denied, no artifact
        was produced, and the phase still reported ``completed``), and
        ``READ_ONLY`` cannot publish a deliverable at all.

        This test exists to pin that the default is a DELIBERATE choice with a
        reason, so that changing it again is a decision rather than an
        accident. A phase wanting less authority declares it today.
        """
        assert DEFAULT_PHASE_SANDBOX is PhaseSandbox.FULL_ACCESS
        argv = _build_codex_command("prompt", "gpt-5.6-sol")
        assert _sandbox_arg(argv) == "danger-full-access"

    def test_a_phase_can_ask_for_less_than_the_default(self) -> None:
        """The point of #1162: authority is declared, not assumed.

        The default being permissive does not make the mechanism pointless -
        a phase that declares ``read-only`` gets it, on every model.
        """
        for model in (None, "gpt-5.6-sol", "haiku"):
            argv = _build_codex_command("prompt", model, PhaseSandbox.READ_ONLY)
            assert _sandbox_arg(argv) == "read-only"


class TestDeclaredLevelIsHonoured:
    @pytest.mark.parametrize(
        ("level", "expected"),
        [
            (PhaseSandbox.READ_ONLY, "read-only"),
            (PhaseSandbox.WORKSPACE_WRITE, "workspace-write"),
            (PhaseSandbox.FULL_ACCESS, "danger-full-access"),
        ],
    )
    def test_each_level_maps_to_its_codex_flag(self, level: PhaseSandbox, expected: str) -> None:
        assert _sandbox_arg(_build_codex_command("p", "gpt-5.6-sol", level)) == expected

    def test_every_level_has_a_flag(self) -> None:
        """A new member without a mapping would KeyError at execution time."""
        for member in PhaseSandbox:
            assert member in CODEX_SANDBOX_FLAGS


class TestUnknownLevelIsRefusedNotDowngraded:
    def test_unknown_value_raises(self) -> None:
        with pytest.raises(UnsupportedPhaseSandboxError) as exc:
            _resolve_sandbox("workspace_write", phase_id="verify")
        assert "verify" in str(exc.value)

    def test_message_names_the_levels_and_recommends_read_only(self) -> None:
        with pytest.raises(UnsupportedPhaseSandboxError) as exc:
            _resolve_sandbox("full", phase_id="verify")
        message = str(exc.value)
        for member in PhaseSandbox:
            assert str(member) in message

    def test_none_falls_back_to_the_default(self) -> None:
        assert _resolve_sandbox(None, phase_id="verify") is DEFAULT_PHASE_SANDBOX


class TestStoredValuesAreNotWidened:
    """A stored template is rehydrated straight from a historical event.

    It never sees the YAML validator, so the execution boundary is the only
    place an invalid level can be refused. Widening one to the write-capable
    default is the failure this class exists to prevent.
    """

    @pytest.mark.parametrize("stored", ["", "Read-Only", " read-only ", "readonly"])
    def test_an_invalid_stored_level_is_refused_not_widened(self, stored: str) -> None:
        with pytest.raises(UnsupportedPhaseSandboxError):
            _resolve_sandbox(stored, phase_id="verify")

    def test_empty_string_survives_config_construction_as_itself(self) -> None:
        """``or`` would turn "" into the default here and lose the refusal."""
        from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
            _build_agent_config_from_phase,
        )

        class _StoredPhase:
            phase_id = "verify"
            model = None
            provider = "codex"
            allow_delegation = False
            allowed_tools: tuple[str, ...] = ()
            sandbox = ""

        config = _build_agent_config_from_phase(_StoredPhase())
        assert config.sandbox == ""
        with pytest.raises(UnsupportedPhaseSandboxError):
            _resolve_sandbox(config.sandbox, phase_id="verify")


class TestTheWholePathFromYaml:
    """The unit tests above call the builder directly and would not notice
    ``sandbox`` being dropped between YAML and the command line. This one
    walks the hops that actually carry it."""

    def test_yaml_read_only_reaches_the_codex_argv(self) -> None:
        from syn_domain.contexts.orchestration._shared.workflow_definition import (
            WorkflowDefinition,
        )

        definition = WorkflowDefinition.from_yaml(
            """
id: sandbox-path
name: sandbox-path
description: verify that a declared level survives every hop
phases:
  - id: verify
    name: Verify
    order: 1
    prompt_template: check the work
    agent:
      provider: codex
      model: gpt-5.6-sol
      sandbox: read-only
"""
        )
        phase = definition.phases[0].to_domain()
        assert phase.sandbox == "read-only", "dropped between YAML and PhaseDefinition"

        argv = _build_codex_command(
            "check the work",
            phase.model,
            _resolve_sandbox(phase.sandbox, phase_id=phase.phase_id),
        )
        assert _sandbox_arg(argv) == "read-only"
