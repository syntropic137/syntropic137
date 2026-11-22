"""A stored agent phase with no prompt is a 422 at execute, never a run (#963).

Authoring refuses a prompt-less agent phase, but two kinds of stored template
never meet that rule: one installed before it, and the placeholder phase a bare
``POST /workflows`` creates (``syn workflow create``) until ``PUT .../phases``
gives it a prompt. Both reach execute through the stored-template check, which
must answer as an HTTP refusal: before #963 the run started with an empty
prompt and billed (#961), and a refusal that escaped as a 500 would hand the
caller nothing to act on.

Everything goes through the real app and the real execute route; only
``execute()`` is replaced, so "launched" means the route handed the request on.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from syn_adapters.maintenance import InMemoryMaintenanceAdapter
from syn_domain.contexts._shared import AdmissionGate

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

    from syn_domain.contexts._shared import AdmissionTicket

pytestmark = [pytest.mark.unit, pytest.mark.anyio]


@pytest.fixture(autouse=True)
def _reset_storage() -> Iterator[None]:
    from syn_adapters.projection_stores import get_projection_store
    from syn_adapters.projections.manager import reset_projection_manager
    from syn_adapters.storage import reset_storage

    reset_storage()
    reset_projection_manager()
    store = get_projection_store()
    if hasattr(store, "_data"):
        store._data.clear()  # pyright: ignore[reportAttributeAccessIssue]  # in-memory store only
    if hasattr(store, "_state"):
        store._state.clear()  # pyright: ignore[reportAttributeAccessIssue]  # in-memory store only
    yield
    reset_storage()
    reset_projection_manager()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    from syn_api.main import create_app

    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as c:
        yield c


class _CapturingExecute:
    """Stands in for `execute()`, counting each launch the route admitted."""

    def __init__(self) -> None:
        self.launched = 0

    async def __call__(self, *, admitted: AdmissionTicket | None = None, **_: object) -> None:
        self.launched += 1
        if admitted is not None:
            admitted.mark_visible()


@pytest.fixture
def execution(monkeypatch: pytest.MonkeyPatch) -> _CapturingExecute:
    import syn_api._wiring_admission as wiring
    from syn_api.routes.executions import commands

    captured = _CapturingExecute()
    monkeypatch.setattr(
        wiring,
        "_admission_gate_singleton",
        AdmissionGate(InMemoryMaintenanceAdapter()),
        raising=False,
    )
    monkeypatch.setattr(commands, "execute", captured)
    return captured


async def _create_workflow(*, prompt: str | None) -> tuple[str, str]:
    """Create through the real route; ``prompt=None`` is a bare create with no phases."""
    from syn_api.routes.workflows import create_workflow
    from syn_api.routes.workflows.queries import get_workflow
    from syn_api.types import Ok

    phases = None if prompt is None else [{"name": "Work", "prompt_template": prompt}]
    created = await create_workflow(
        name="Prompt #963", workflow_type="research", requires_repos=False, phases=phases
    )
    assert isinstance(created, Ok)
    workflow_id = created.value.workflow_id
    detail = await get_workflow(workflow_id)
    assert isinstance(detail, Ok)
    return workflow_id, detail.value.phases[0].phase_id


async def test_a_bare_create_is_refused_at_execute_naming_its_phase(
    client: AsyncClient, execution: _CapturingExecute
) -> None:
    workflow_id, phase_id = await _create_workflow(prompt=None)

    response = await client.post(f"/workflows/{workflow_id}/execute", json={})

    assert response.status_code == 422, response.text
    assert f"Phase '{phase_id}' (kind: agent)" in response.text
    assert "needs 'prompt_template' or 'prompt_file'" in response.text
    assert execution.launched == 0


async def test_the_same_workflow_runs_once_its_phase_has_a_prompt(
    client: AsyncClient, execution: _CapturingExecute
) -> None:
    workflow_id, phase_id = await _create_workflow(prompt=None)
    updated = await client.put(
        f"/workflows/{workflow_id}/phases/{phase_id}",
        json={"prompt_template": "Summarise the repository."},
    )
    assert updated.status_code == 200, updated.text

    response = await client.post(f"/workflows/{workflow_id}/execute", json={})

    assert response.status_code == 200, response.text
    assert execution.launched == 1
