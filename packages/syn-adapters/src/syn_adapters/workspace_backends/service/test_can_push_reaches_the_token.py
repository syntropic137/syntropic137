"""`can_push: false` in a workflow reaches the token GitHub mints (#1161).

The unit tests beside `client_token` pin the request. This one pins the HOPS,
because that is where this class of change dies: a declaration parsed
correctly, carried through four value objects, and dropped at the one call that
would have acted on it. Every object in between looks right at both ends.

So the assertion is on `_resolve_github_auth`'s effect - what scope the client
was asked for - starting from the YAML text a workflow author writes.

Run: pytest -m unit packages/syn-adapters/src/syn_adapters/workspace_backends/service/test_can_push_reaches_the_token.py -v
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from syn_adapters.workspace_backends.service.setup_phase_secrets import SetupPhaseSecrets
from syn_domain.contexts.orchestration._shared.workflow_definition import PhaseYamlDefinition

pytestmark = pytest.mark.unit

REPO = "https://github.com/syntropic137/syntropic137"

# Verbatim from workflows/sdlc/implement/workflow.yaml's verify phase, trimmed
# to the keys under test. `can_push: false` is a value that cannot arise by
# default: the field defaults to True everywhere it is declared.
VERIFY_PHASE_YAML = """
id: verify
name: Verify the change independently
order: 3
timeout_seconds: 3600
can_push: false
agent:
  provider: codex
  model: gpt-5.6-sol
"""

IMPLEMENT_PHASE_YAML = """
id: implement
name: Make the change
order: 2
timeout_seconds: 3600
allowed_tools: [Read, Bash, Edit, Write]
agent:
  provider: claude
  model: opus
"""


def _phase(yaml_text: str):
    """Parse a phase the way workflow installation does."""
    return PhaseYamlDefinition.model_validate(yaml.safe_load(yaml_text)).to_domain()


async def _scope_requested(*, can_push: bool) -> bool:
    """Provision with `can_push` and report whether a READ-ONLY token was asked for."""
    client = MagicMock()
    client.get_installation_for_repo = AsyncMock(return_value="12345")
    client.get_installation_token = AsyncMock(return_value="ghs_x")

    settings = MagicMock()
    settings.is_configured = True
    settings.bot_name = "syntropic137-swe-mini[bot]"
    settings.bot_email = "bot@example.com"

    module = "syn_adapters.workspace_backends.service.setup_phase_secrets"
    with (
        patch(f"{module}.GitHubAppNotConfiguredError"),
        patch("syn_adapters.github.GitHubAppClient", return_value=client),
        patch("syn_shared.settings.github.GitHubAppSettings", return_value=settings),
    ):
        await SetupPhaseSecrets.create(repositories=[REPO], can_push=can_push)

    client.get_installation_token.assert_awaited_once()
    return bool(client.get_installation_token.await_args.kwargs["read_only"])


@pytest.mark.asyncio
async def test_the_verify_phases_declaration_reaches_the_mint_call() -> None:
    """The end of the chain, driven from the start of it.

    Every hop between is exercised for real - YAML parse, PhaseDefinition, the
    keyword that `WorkspaceProvisionHandler` forwards - so a future refactor
    that drops `can_push` at any one of them fails here rather than in
    production, where the only symptom is a verify phase that can push again
    and a report that reads exactly as it does today.
    """
    phase = _phase(VERIFY_PHASE_YAML)
    assert phase.can_push is False, "the declaration was lost parsing the YAML"

    assert await _scope_requested(can_push=phase.can_push) is True


@pytest.mark.asyncio
async def test_a_phase_that_must_push_still_gets_a_writing_token() -> None:
    """The other half: the fix must not disarm the phase that does the work.

    `workspace-write` as a default is what broke every codex phase in
    v0.28.0-beta.5. A control that quietly removes the implement phase's push
    access fails the same way, and would look identical until a PR failed to
    appear.
    """
    phase = _phase(IMPLEMENT_PHASE_YAML)
    assert phase.can_push is True

    assert await _scope_requested(can_push=phase.can_push) is False
