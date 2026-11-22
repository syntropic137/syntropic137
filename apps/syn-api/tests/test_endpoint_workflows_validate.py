"""POST /workflows/validate reports a retired phase key as an error (#1502).

Unmocked: the real validator refuses the key and its message, naming the key
and why, reaches the response, so `syn workflow validate` tells an author
which line to delete.
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


async def test_a_retired_key_is_invalid() -> None:
    result = await validate_yaml_endpoint(ValidateYamlRequest(content=RETIRED_KEY_YAML))

    assert result.valid is False
    assert len(result.errors) == 1
    assert "'can_open_pr' is retired" in result.errors[0]
    assert "'open_pr'" in result.errors[0]
    assert result.warnings == []


async def test_a_clean_workflow_is_valid() -> None:
    clean = RETIRED_KEY_YAML.replace("    can_open_pr: true\n", "")

    result = await validate_yaml_endpoint(ValidateYamlRequest(content=clean))

    assert result.valid is True
    assert result.errors == []
    assert result.warnings == []


@pytest.mark.parametrize("content", ["phases: [unclosed", "- a"])
async def test_malformed_yaml_is_invalid_not_a_server_error(content: str) -> None:
    result = await validate_yaml_endpoint(ValidateYamlRequest(content=content))

    assert result.valid is False
    assert result.warnings == []
