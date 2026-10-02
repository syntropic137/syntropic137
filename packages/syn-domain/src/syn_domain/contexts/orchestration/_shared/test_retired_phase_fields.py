"""A retired phase key is accepted, ignored and reported - and only by name.

`can_open_pr` has done nothing since #1477. YAML written against the older
schema must still load, so the key is dropped before `extra="forbid"` sees it.
The drop is by name: every other unknown key is still refused (#961).
"""

from __future__ import annotations

import pytest
import yaml
from pydantic import ValidationError

from syn_domain.contexts.orchestration import retired_field_notices
from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
    PhaseDefinition,
)

pytestmark = pytest.mark.unit


def _workflow(phase_extra: str) -> str:
    return f"""
id: retired-wf
name: Retired
type: custom
classification: simple
phases:
  - id: open_pr
    name: Open PR
    order: 1
    prompt_template: "Open the PR."
{phase_extra}"""


class TestTheKeyStillLoads:
    def test_a_workflow_carrying_the_key_still_loads(self) -> None:
        definition = WorkflowDefinition.from_yaml(_workflow("    can_open_pr: true\n"))

        assert [p.id for p in definition.phases] == ["open_pr"]
        assert "can_open_pr" not in PhaseDefinition.model_fields
        assert "can_open_pr" not in definition.get_domain_phases()[0].model_dump()

    @pytest.mark.parametrize("value", ["false", "null", '"banana"'])
    def test_any_value_is_ignored(self, value: str) -> None:
        """The value is never typed, so no value can fail the load."""
        content = _workflow(f"    can_open_pr: {value}\n")

        WorkflowDefinition.from_yaml(content)

        assert len(retired_field_notices(yaml.safe_load(content))) == 1

    def test_a_misspelt_key_is_still_refused(self) -> None:
        """Dropping by name, not `extra="ignore"`: #961 stays closed."""
        with pytest.raises(ValidationError, match="can_open_prr"):
            WorkflowDefinition.from_yaml(_workflow("    can_open_prr: true\n"))


class TestNotices:
    def test_notices_name_phase_and_key(self) -> None:
        notices = retired_field_notices(yaml.safe_load(_workflow("    can_open_pr: true\n")))

        assert len(notices) == 1
        assert "'open_pr'" in notices[0]
        assert "'can_open_pr'" in notices[0]
        assert "#1477" in notices[0]

    def test_a_clean_workflow_has_none(self) -> None:
        assert retired_field_notices(yaml.safe_load(_workflow(""))) == []

    @pytest.mark.parametrize(
        "definition",
        [None, ["a"], {"name": "no phases"}, {"phases": "x"}, {"phases": ["x", None]}],
    )
    def test_notices_never_raise_on_odd_input(self, definition: object) -> None:
        assert retired_field_notices(definition) == []
