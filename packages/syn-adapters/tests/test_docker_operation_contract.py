"""Docker-backed evidence for the provider operation contract (plan §7 row 7).

Real ``WorkspaceDockerProvider``, real container. Run with:

    SYN_CONTRACT_TEST_IMAGE=busybox:1.36 \
      uv run pytest -m integration packages/syn-adapters/tests/test_docker_operation_contract.py

The credential reaches the workload's environment through a binding resolved
by ``WorkspaceCredentials``, and is absent from the docker argv, the labels and
the provider's logs. The agent stream reaches the workload through
``start``/``observe`` and keeps its launch marker and exit status.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from typing import TYPE_CHECKING

import pytest
from agentic_isolation import (
    SecurityConfig,
    WorkspaceConfig,
    WorkspaceDockerProvider,
    WorkspaceRuntime,
)

from syn_adapters.workspace_backends.agentic.credentials import WorkspaceCredentials
from syn_adapters.workspace_backends.agentic.session_store_env import (
    session_store_credential_bindings,
)
from syn_adapters.workspace_backends.agentic.stream_adapter import AgenticEventStreamAdapter
from syn_domain.contexts.orchestration import announce_as
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    IsolationHandle,
)
from syn_shared.env_constants import ENV_AGENTIC_SESSION_STORE_AUTH
from syn_shared.settings.session_store import SessionStoreSettings

if TYPE_CHECKING:
    from pathlib import Path

    from agentic_isolation.providers.base import Workspace

IMAGE = os.environ.get("SYN_CONTRACT_TEST_IMAGE")
_TOKEN = "synthetic-store-token-0b6f2c"
_GRANT = "synpt_SYNTHETIC_GRANT_0b6f2c"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not IMAGE, reason="Set SYN_CONTRACT_TEST_IMAGE to any image with sh"),
]


class _Host:
    def __init__(
        self,
        provider: WorkspaceDockerProvider,
        workspace: Workspace,
        credentials: WorkspaceCredentials,
    ) -> None:
        self.operations = provider
        self.credentials = credentials
        self._workspace = workspace

    def workspace(self, isolation_id: str) -> Workspace | None:
        return self._workspace


async def test_bound_credentials_reach_the_workload_and_nothing_else(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    assert IMAGE is not None
    settings = SessionStoreSettings(
        _env_file=None,
        url="http://store.invalid",
        auth_token=_TOKEN,  # type: ignore[arg-type]
    )
    credentials = WorkspaceCredentials(settings)
    provider = WorkspaceDockerProvider(
        default_image=IMAGE,
        default_network="none",
        workspace_base_dir=tmp_path / "workspaces",
        security=SecurityConfig(runtime=WorkspaceRuntime.RUNC),
        credentials=credentials,
    )
    caplog.set_level(logging.DEBUG)
    workspace = await provider.create(
        WorkspaceConfig(
            provider="docker",
            image=IMAGE,
            credentials=session_store_credential_bindings(settings),
            labels={"syn.test": "operation-contract"},
        )
    )
    try:
        handle = IsolationHandle(isolation_id=workspace.id, isolation_type="docker")
        adapter = AgenticEventStreamAdapter(_Host(provider, workspace, credentials))  # type: ignore[arg-type]
        wrapper = "syn-contract-wrapper-0b6f2c"
        lines = [
            line
            async for line in adapter.stream(
                handle,
                [
                    "sh",
                    "-c",
                    f'echo "store=${ENV_AGENTIC_SESSION_STORE_AUTH}"; echo "grant=$SYN_API_TOKEN"; '
                    "exit 7",
                ],
                environment={"SYN_API_TOKEN": _GRANT, "SYN_API_URL": "http://x"},
                wrapper_name=wrapper,
                timeout_seconds=60,
            )
        ]

        assert lines[0] == announce_as(wrapper), "the launch marker is the first line"
        assert f"store={_TOKEN}" in lines
        assert f"grant={_GRANT}" in lines
        assert adapter.last_exit_code == 7

        inspected = json.loads(
            subprocess.run(
                ["docker", "inspect", workspace.metadata.get("container_id", workspace.id)],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        )[0]
        labels = json.dumps(inspected["Config"].get("Labels") or {})
        assert _TOKEN not in labels and _GRANT not in labels
        assert _TOKEN not in json.dumps(inspected["Args"]) + inspected["Path"]
        ps = subprocess.run(["ps", "axww"], capture_output=True, text=True, check=False).stdout
        assert _TOKEN not in ps and _GRANT not in ps, "no client argv carries a value"
        assert _TOKEN not in caplog.text and _GRANT not in caplog.text
    finally:
        await provider.teardown(target=workspace)
