"""A codex phase's agent env carries no codex credential, in any form (#1971).

The OpenAI key reaches the workspace only as the staged ~/.codex/auth.json. The
env the agent process is launched with is built by `_launch_for`; this drives it
with real settings holding every credential at once.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
    WorkspaceProvisionHandler,
)
from syn_shared.env_constants import (
    ENV_ANTHROPIC_API_KEY,
    ENV_CODEX_AUTH_JSON,
    ENV_OPENAI_API_KEY,
)
from syn_shared.settings import reset_settings

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

_KEY = "sk-proj-FAKEagentEnv0000_tail1111"
_AUTH_JSON = '{"auth_mode":"chatgpt","tokens":{"access_token":"FAKEaccess0000"}}'
_ANTHROPIC = "sk-ant-FAKEanthropic0000"


@pytest.fixture
def every_credential(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv(ENV_OPENAI_API_KEY, _KEY)
    monkeypatch.setenv(ENV_CODEX_AUTH_JSON, _AUTH_JSON)
    monkeypatch.setenv(ENV_ANTHROPIC_API_KEY, _ANTHROPIC)
    reset_settings()
    yield
    reset_settings()


def _phase(allow_delegation: bool) -> ExecutablePhase:
    return ExecutablePhase(
        phase_id="review",
        name="Review",
        order=1,
        prompt_template="review it",
        agent_config=AgentConfiguration(provider="codex", allow_delegation=allow_delegation),
    )


@pytest.mark.parametrize("allow_delegation", [False, True])
@pytest.mark.usefixtures("every_credential")
async def test_codex_agent_env_holds_no_codex_credential(allow_delegation: bool) -> None:
    workspace = MagicMock()
    workspace.proxy_url = "http://envoy:10000"
    workspace.workspace_id = "ws-1971"
    workspace.inject_files = AsyncMock()
    handler = WorkspaceProvisionHandler(
        workspace_service=MagicMock(),
        prompt_builder=AsyncMock(return_value="review it"),
        command_builder=lambda _phase, prompt: ["codex", "exec", prompt],
    )

    command, env = await handler._launch_for(
        _phase(allow_delegation), "review it", workspace, "sess-1971", []
    )

    assert ENV_OPENAI_API_KEY not in env
    assert ENV_CODEX_AUTH_JSON not in env
    flat = " ".join([*command, *env.keys(), *env.values()])
    assert _KEY not in flat
    assert "FAKEaccess0000" not in flat
