"""#2391: a command phase installed the way `syn workflow install` does reads back with its steps.

`GET /workflows/{id}` returned `commands: []` for a phase whose steps were
stored and ran. The steps reached the aggregate intact; the read model
dropped them, because the projection is handed a Python-mode dump of the
event, where a ``tuple`` field stays a tuple, and the stored-row reader only
accepted a list. Every check before this one stopped at the aggregate, so
this goes from the CLI's upload body to the HTTP read and nothing shorter.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

# What `syn workflow install` uploads: the YAML as JSON, to /workflows/from-yaml
# (apps/syn-cli-node/src/client/yaml-upload.ts). Every step field departs from
# its default somewhere, so a mapping that drops one cannot pass by default.
_BODY = {
    "id": "probe-command-phase-v1",
    "name": "Command phase probe",
    "type": "custom",
    "classification": "simple",
    "requires_repos": False,
    "phases": [
        {
            "id": "build",
            "name": "Build",
            "order": 1,
            "kind": "command",
            "timeout_seconds": 600,
            "commands": [
                {"name": "one", "run": "echo 1"},
                {"name": "two", "run": "echo 2", "timeout_seconds": 30},
                {"name": "three", "run": "exit 1", "allow_failure": True},
            ],
        }
    ],
}


@pytest.fixture(autouse=True)
def _reset_storage() -> Iterator[None]:
    from syn_adapters.projections.manager import reset_projection_manager
    from syn_adapters.storage import reset_storage

    reset_storage()
    reset_projection_manager()
    yield
    reset_storage()
    reset_projection_manager()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    from syn_api.main import create_app

    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as c:
        yield c


async def test_a_command_phase_reads_back_every_step_it_was_installed_with(
    client: AsyncClient,
) -> None:
    created = await client.post("/workflows/from-yaml", json=_BODY)
    assert created.status_code == 201, created.text

    detail = await client.get("/workflows/probe-command-phase-v1")
    assert detail.status_code == 200, detail.text

    (phase,) = detail.json()["phases"]
    assert phase["kind"] == "command"
    assert phase["commands"] == [
        {"name": "one", "run": "echo 1", "timeout_seconds": None, "allow_failure": False},
        {"name": "two", "run": "echo 2", "timeout_seconds": 30, "allow_failure": False},
        {"name": "three", "run": "exit 1", "timeout_seconds": None, "allow_failure": True},
    ]
