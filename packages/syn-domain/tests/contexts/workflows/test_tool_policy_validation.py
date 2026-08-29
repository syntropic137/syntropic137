"""Authoring-time validation for phase tool/token declarations (issue #964).

Both defects here are the same shape: a field an author writes, that renders
in the UI, and that changes nothing at execution. Catching them at parse time
is the difference between "your workflow is wrong" and "your unattended CI
trigger behaved differently than you designed".
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from syn_shared.tools import ToolName

pytestmark = pytest.mark.unit


def _phase(**overrides):
    from syn_domain.contexts.orchestration._shared.workflow_definition import (
        PhaseYamlDefinition,
    )

    payload = {"id": "research", "name": "research", "order": 1, "prompt_template": "do the thing"}
    payload.update(overrides)
    return PhaseYamlDefinition(**payload)


class TestToolNamesAreAClosedVocabulary:
    def test_case_is_forgiven_because_every_shipped_workflow_got_it_wrong(self) -> None:
        """`bash` -> `Bash`. The intent is unambiguous; the CLI is case-sensitive."""
        phase = _phase(allowed_tools=["bash", "read"])

        assert phase.allowed_tools == [ToolName.BASH, ToolName.READ]

    def test_an_unknown_tool_is_rejected_at_authoring_time(self) -> None:
        """`git` is not a Claude tool - the field's own docstring suggested it."""
        with pytest.raises(ValidationError) as exc:
            _phase(allowed_tools=["bash", "git"])

        assert "git" in str(exc.value)

    def test_the_error_names_the_valid_options(self) -> None:
        with pytest.raises(ValidationError) as exc:
            _phase(allowed_tools=["Wget"])

        assert "Bash" in str(exc.value)

    def test_a_comma_separated_string_still_parses(self) -> None:
        """The field has always accepted a string; that must keep working."""
        phase = _phase(allowed_tools="bash, read")

        assert phase.allowed_tools == [ToolName.BASH, ToolName.READ]

    def test_omitting_the_field_declares_no_policy(self) -> None:
        assert _phase().allowed_tools == []


class TestMaxTokensIsRefusedRatherThanIgnored:
    def test_declaring_max_tokens_fails_because_no_harness_can_enforce_it(self) -> None:
        """Neither CLI has a token-cap flag.

        Verified against claude 2.1.251 (which offers --max-budget-usd, in
        DOLLARS, not tokens) and codex 0.147.0 (which offers neither). A field
        that renders in the UI and caps nothing is worse than no field: it is
        the control an author reaches for to bound an expensive fan-out.
        """
        with pytest.raises(ValidationError) as exc:
            _phase(max_tokens=4096)

        assert "max_tokens" in str(exc.value)

    def test_the_error_points_at_a_control_that_does_exist(self) -> None:
        with pytest.raises(ValidationError) as exc:
            _phase(max_tokens=4096)

        assert "timeout_seconds" in str(exc.value)

    def test_omitting_max_tokens_is_the_supported_path(self) -> None:
        assert _phase().max_tokens is None
