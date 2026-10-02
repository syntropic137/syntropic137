"""A retired phase key loads, does nothing, and is reported (#1477 follow-up).

`can_open_pr` stopped deciding anything in #1477. It is no longer a field, but
YAML written before that still carries it, so it is dropped by name and each
occurrence becomes a notice. Every other unknown key is still refused (#961).
"""

from __future__ import annotations

import pytest
import yaml
from pydantic import ValidationError

from syn_domain.contexts.orchestration._shared.retired_phase_fields import (
    retired_field_notices,
)
from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
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


class TestARetiredKeyStillLoads:
    def test_a_workflow_carrying_the_key_still_loads(self) -> None:
        definition = WorkflowDefinition.from_yaml(_workflow("can_open_pr: true"))

        assert [p.id for p in definition.phases] == ["open_pr"]
        assert "can_open_pr" not in PhaseDefinition.model_fields
        assert "can_open_pr" not in definition.phases[0].to_domain().model_dump()

    @pytest.mark.parametrize("value", ["false", "null", '"banana"'])
    def test_any_value_is_ignored(self, value: str) -> None:
        """The value is never read, so no value can be wrong."""
        text = _workflow(f"can_open_pr: {value}")

        WorkflowDefinition.from_yaml(text)

        assert len(retired_field_notices(yaml.safe_load(text))) == 1

    def test_a_misspelt_key_is_still_refused(self) -> None:
        """The drop is by name. `extra="ignore"` would reopen #961."""
        with pytest.raises(ValidationError, match="can_open_prr"):
            WorkflowDefinition.from_yaml(_workflow("can_open_prr: true"))


class TestNotices:
    def test_notices_name_phase_and_key(self) -> None:
        notices = retired_field_notices(yaml.safe_load(_workflow("can_open_pr: true")))

        assert len(notices) == 1
        assert "'open_pr'" in notices[0]
        assert "'can_open_pr'" in notices[0]
        assert "#1477" in notices[0]

    def test_a_clean_workflow_has_none(self) -> None:
        assert retired_field_notices(yaml.safe_load(_workflow())) == []

    @pytest.mark.parametrize(
        "parsed",
        [None, ["a"], "phases", {"name": "no phases"}, {"phases": "x"}, {"phases": ["x", None]}],
    )
    def test_notices_never_raise_on_odd_input(self, parsed: object) -> None:
        """Called on whatever the author wrote, before anything validated it."""
        assert retired_field_notices(parsed) == []
