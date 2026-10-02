"""POST /workflows/validate reports a retired phase key as a warning, not an error.

Unmocked: the whole point is that the real validator accepts the key and the
real notice reaches the response, so `syn workflow validate` can tell an
author the line does nothing (#1477 follow-up).
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("APP_ENVIRONMENT", "test")

from syn_api.routes.workflows.commands import ValidateYamlRequest, validate_yaml_endpoint

pytestmark = pytest.mark.unit

RETIRED_KEY_YAML = """
id: retired-wf
name: Retired Key Workflow
type: custom
phases:
  - id: open_pr
    name: Open PR
    order: 1
    prompt_template: "Open it."
    can_open_pr: true
"""


async def test_a_retired_key_is_valid_with_a_warning() -> None:
    result = await validate_yaml_endpoint(ValidateYamlRequest(content=RETIRED_KEY_YAML))

    assert result.valid is True
    assert result.errors == []
    assert len(result.warnings) == 1
    assert "'can_open_pr'" in result.warnings[0]
    assert "'open_pr'" in result.warnings[0]


async def test_a_clean_workflow_has_no_warnings() -> None:
    clean = RETIRED_KEY_YAML.replace("    can_open_pr: true\n", "")

    result = await validate_yaml_endpoint(ValidateYamlRequest(content=clean))

    assert result.valid is True
    assert result.warnings == []


@pytest.mark.parametrize("content", ["phases: [unclosed", "- a"])
async def test_malformed_yaml_is_invalid_not_a_server_error(content: str) -> None:
    """Notices are computed before validity is known, so they must not raise."""
    result = await validate_yaml_endpoint(ValidateYamlRequest(content=content))

    assert result.valid is False
    assert result.warnings == []
