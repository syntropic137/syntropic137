"""A retired phase key is refused at authoring time, by name (#1502).

`can_open_pr` stopped deciding anything in #1477. It was then accepted with a
warning for a deprecation window; now it is refused, with a message naming the
phase, the key and why. Every other unknown key is still refused generically
(#961), and stored events keep replaying it (`REMOVED_EXECUTABLE_PHASE_KEYS`).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from syn_domain.contexts.orchestration._shared.retired_phase_fields import (
    RETIRED_PHASE_FIELDS,
    reject_retired_fields,
)
from syn_domain.contexts.orchestration._shared.workflow_definition import (
    WorkflowDefinition,
    validate_workflow_yaml,
)
from syn_domain.contexts.orchestration._shared.WorkflowValueObjects import PhaseDefinition

pytestmark = pytest.mark.unit


def _workflow(phase_line: str = "") -> str:
    """A minimal valid workflow whose one phase carries `phase_line` verbatim."""
    extra = f"    {phase_line}\n" if phase_line else ""
    return (
        "id: retired-probe\n"
        "name: Retired probe\n"
        "type: custom\n"
        "phases:\n"
        "  - id: open_pr\n"
        "    name: Open PR\n"
        "    order: 1\n"
        "    prompt_template: do the thing\n" + extra
    )


class TestARetiredKeyIsRefused:
    def test_a_workflow_carrying_the_key_is_refused(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            WorkflowDefinition.from_yaml(_workflow("can_open_pr: true"))

        message = str(excinfo.value)
        assert "'can_open_pr' is retired (#1477)" in message
        assert "'open_pr'" in message
        assert "Delete the line" in message
        assert "Extra inputs are not permitted" not in message, (
            "the retired key must be named with its reason, not refused generically"
        )

    @pytest.mark.parametrize("value", ["true", "false", "null", '"banana"'])
    def test_any_value_is_refused(self, value: str) -> None:
        """The key itself is retired; no value makes it acceptable."""
        with pytest.raises(ValidationError, match="'can_open_pr' is retired"):
            WorkflowDefinition.from_yaml(_workflow(f"can_open_pr: {value}"))

    def test_validate_reports_it_as_an_error(self) -> None:
        """What `syn workflow validate` and the validate endpoint read."""
        is_valid, error = validate_workflow_yaml(_workflow("can_open_pr: true"))

        assert is_valid is False
        assert error is not None
        assert "'can_open_pr' is retired" in error

    def test_a_clean_workflow_still_loads(self) -> None:
        definition = WorkflowDefinition.from_yaml(_workflow())

        assert [p.id for p in definition.phases] == ["open_pr"]
        assert "can_open_pr" not in PhaseDefinition.model_fields

    def test_a_misspelt_key_is_still_refused_generically(self) -> None:
        """The retired message is by name. `extra="ignore"` would reopen #961."""
        with pytest.raises(ValidationError, match="can_open_prr") as excinfo:
            WorkflowDefinition.from_yaml(_workflow("can_open_prr: true"))

        assert "is retired" not in str(excinfo.value)


class TestRejectRetiredFields:
    def test_every_retired_key_is_named(self) -> None:
        phase = {"id": "p", **{field.name: True for field in RETIRED_PHASE_FIELDS}}

        with pytest.raises(ValueError) as excinfo:
            reject_retired_fields(phase)

        for field in RETIRED_PHASE_FIELDS:
            assert f"{field.name!r} is retired ({field.retired_by})" in str(excinfo.value)
            assert field.reason in str(excinfo.value)

    def test_a_clean_phase_is_returned_unchanged(self) -> None:
        phase = {"id": "p", "name": "P"}

        assert reject_retired_fields(phase) is phase

    @pytest.mark.parametrize("value", [None, ["a"], "phase", 3])
    def test_a_non_mapping_is_left_for_the_model_to_refuse(self, value: object) -> None:
        assert reject_retired_fields(value) is value
