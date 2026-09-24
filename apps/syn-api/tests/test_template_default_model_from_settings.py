"""Every template-creating API path applies SYN_DEFAULT_*_MODEL (R1).

The domain handler takes the defaults as a required argument, so a path that
forgot them would not even construct. What that cannot catch is a path that
passes the STATIC fallbacks instead of the operator's settings - these tests
set non-default values and read back what was persisted.

Paths covered here: the JSON create route, the YAML install route, and the
offline demo seeder. The two seed scripts (scripts/seed_workflows.py,
scripts/seed_triggers.py) build the same handler from the same
``get_settings().phase_model_defaults``.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from syn_api.types import Ok
from syn_shared.agents import AgentProvider, ModelAlias

if TYPE_CHECKING:
    from collections.abc import Iterator

os.environ.setdefault("APP_ENVIRONMENT", "test")

pytestmark = pytest.mark.unit

CLAUDE_SETTING = ModelAlias.SONNET
CODEX_SETTING = "gpt-operator-choice"

_YAML = f"""
id: defaults-from-yaml
name: Defaults from YAML
type: custom
requires_repos: false
phases:
  - id: write
    name: Write
    order: 1
    prompt_template: write it
  - id: review
    name: Review
    order: 2
    prompt_template: review it
    agent:
      provider: {AgentProvider.CODEX}
"""


@pytest.fixture(autouse=True)
def _reset_storage() -> Iterator[None]:
    from syn_adapters.projections.manager import reset_projection_manager
    from syn_adapters.storage import reset_storage

    reset_storage()
    reset_projection_manager()
    yield
    reset_storage()
    reset_projection_manager()


@pytest.fixture(autouse=True)
def _operator_defaults() -> Iterator[None]:
    from syn_shared.settings import reset_settings

    keys = ("SYN_DEFAULT_CLAUDE_MODEL", "SYN_DEFAULT_CODEX_MODEL")
    previous = {key: os.environ.get(key) for key in keys}
    os.environ["SYN_DEFAULT_CLAUDE_MODEL"] = CLAUDE_SETTING
    os.environ["SYN_DEFAULT_CODEX_MODEL"] = CODEX_SETTING
    reset_settings()
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        reset_settings()


async def _stored_models(workflow_id: str) -> dict[str, str | None]:
    from syn_api._wiring import get_workflow_repo

    aggregate = await get_workflow_repo().get_by_id(workflow_id)
    assert aggregate is not None
    return {phase.phase_id: phase.model for phase in aggregate.phases}


async def test_the_create_route_persists_the_configured_defaults() -> None:
    from syn_api.routes.workflows import create_workflow

    result = await create_workflow(
        name="Defaults from JSON",
        workflow_id="defaults-from-json",
        phases=[
            {"phase_id": "write", "name": "Write", "order": 1, "prompt_template": "x"},
            {
                "phase_id": "review",
                "name": "Review",
                "order": 2,
                "prompt_template": "x",
                "agent": {"provider": AgentProvider.CODEX},
            },
        ],
    )
    assert isinstance(result, Ok)

    assert await _stored_models("defaults-from-json") == {
        "write": CLAUDE_SETTING,
        "review": CODEX_SETTING,
    }


async def test_the_yaml_install_route_persists_the_configured_defaults() -> None:
    from syn_api.routes.workflows.commands import create_workflow_from_yaml

    assert isinstance(await create_workflow_from_yaml(_YAML), Ok)

    assert await _stored_models("defaults-from-yaml") == {
        "write": CLAUDE_SETTING,
        "review": CODEX_SETTING,
    }


async def test_the_offline_seeder_persists_the_configured_defaults() -> None:
    from syn_api.services.seeding import _seed_workflow_templates

    await _seed_workflow_templates()

    models = await _stored_models("self-heal-pr")
    assert models
    assert set(models.values()) == {CLAUDE_SETTING}


async def _create_then_switch_to_codex() -> None:
    from syn_api.routes.workflows import create_workflow
    from syn_api.routes.workflows.commands import update_phase_prompt

    created = await create_workflow(
        name="Switch",
        workflow_id="switch",
        phases=[{"phase_id": "p", "name": "P", "order": 1, "prompt_template": "x"}],
    )
    assert isinstance(created, Ok)
    assert await _stored_models("switch") == {"p": CLAUDE_SETTING}

    edited = await update_phase_prompt(
        "switch", "p", prompt_template="y", provider=AgentProvider.CODEX
    )
    assert isinstance(edited, Ok)


async def test_a_provider_switch_edit_stores_the_configured_codex_default() -> None:
    """The phase-edit route applies the same rule as install."""
    await _create_then_switch_to_codex()

    assert await _stored_models("switch") == {"p": CODEX_SETTING}


# WorkflowPhaseUpdated is not wired into the projection manager, so no phase
# edit reaches the detail projection that export reads. Strict, so this flips
# the day #444 is fixed.
@pytest.mark.xfail(strict=True, reason="TODO(#444): phase edits never reach the projection")
async def test_a_provider_switch_edit_reaches_the_export() -> None:
    from syn_api.routes.workflows import export_workflow

    await _create_then_switch_to_codex()

    exported = await export_workflow("switch", fmt="package")
    assert isinstance(exported, Ok)
    assert f"model: {CODEX_SETTING}" in exported.value.files["phases/p.md"]
