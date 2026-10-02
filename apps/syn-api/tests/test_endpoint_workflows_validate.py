"""POST /workflows/validate: retired-key warnings, and bad YAML stays a 200.

Not mocked: these drive `validate_yaml_endpoint` through the real
`validate_yaml`, because the wiring under test is the endpoint carrying what
the service derived. A test that patched the service would pass with the
endpoint dropping `warnings` on the floor.
"""

from __future__ import annotations

import pytest

from syn_api.routes.workflows.commands import ValidateYamlRequest, validate_yaml_endpoint

pytestmark = pytest.mark.unit

_WITH_RETIRED_KEY = """
id: retired-key-wf
name: Retired Key
type: custom
classification: simple
phases:
  - id: open_pr
    name: Open PR
    order: 1
    prompt_template: "Open the PR."
    can_open_pr: true
"""


async def test_retired_key_is_valid_with_a_warning() -> None:
    result = await validate_yaml_endpoint(ValidateYamlRequest(content=_WITH_RETIRED_KEY))

    assert result.valid is True
    assert result.errors == []
    assert len(result.warnings) == 1
    assert "'open_pr'" in result.warnings[0]
    assert "can_open_pr" in result.warnings[0]


async def test_without_the_key_there_is_no_warning() -> None:
    content = _WITH_RETIRED_KEY.replace("    can_open_pr: true\n", "")
    result = await validate_yaml_endpoint(ValidateYamlRequest(content=content))

    assert result.valid is True
    assert result.warnings == []


async def test_a_misspelt_key_is_still_invalid() -> None:
    """The drop is by name: #961 must stay closed."""
    content = _WITH_RETIRED_KEY.replace("can_open_pr:", "can_open_prr:")
    result = await validate_yaml_endpoint(ValidateYamlRequest(content=content))

    assert result.valid is False
    assert any("can_open_prr" in e for e in result.errors)


@pytest.mark.parametrize("content", ["phases: [unclosed", "- a"])
async def test_malformed_yaml_is_invalid_not_a_server_error(content: str) -> None:
    """A second parse for notices must never turn `valid: false` into a 500."""
    result = await validate_yaml_endpoint(ValidateYamlRequest(content=content))

    assert result.valid is False
    assert result.errors
    assert result.warnings == []
