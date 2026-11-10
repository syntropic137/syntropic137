"""A stored rule with no GitHub installation says it is unable to fire (#2202).

#2201 refuses to create such a rule, but rules stored before it can still be
``active`` with ``installation_id=""``. The poller skips them on every cycle,
so the read path has to say so: these tests go through the HTTP endpoint
functions over the real trigger query store, because a reason computed in the
service and dropped when the response is built would pass a service-level test.
"""

from __future__ import annotations

import os

import pytest

from syn_api.routes.triggers.queries import get_trigger_endpoint, list_triggers_endpoint
from syn_domain.contexts.github.domain.aggregate_trigger.TriggerConfig import TriggerConfig

pytestmark = pytest.mark.unit

os.environ.setdefault("APP_ENVIRONMENT", "test")


@pytest.fixture(autouse=True)
def _reset_trigger_store():
    from syn_domain.contexts.github.slices.register_trigger.trigger_store import (
        reset_trigger_store,
    )

    reset_trigger_store()
    yield
    reset_trigger_store()


async def _store(trigger_id: str, repository: str, installation_id: str) -> None:
    """Index a rule as a pre-#2201 registration could have left it."""
    from syn_api._wiring import ensure_connected, get_trigger_store

    await ensure_connected()
    await get_trigger_store().index_trigger(
        trigger_id=trigger_id,
        name=trigger_id,
        event="push",
        repository=repository,
        workflow_id="wf-1",
        conditions=[],
        input_mapping={},
        config=TriggerConfig(),
        installation_id=installation_id,
        created_by="test",
        status="active",
    )


async def _listed() -> dict[str, str | None]:
    resp = await list_triggers_endpoint(repository=None, status=None)
    return {t.trigger_id: t.unable_to_fire_reason for t in resp.triggers}


async def test_a_rule_with_a_repository_and_no_installation_is_unable_to_fire() -> None:
    await _store("tr-dead", "acme/widgets", "")
    await _store("tr-live", "acme/gadgets", "inst-42")

    listed = await _listed()
    assert listed["tr-live"] is None
    reason = listed["tr-dead"]
    assert reason is not None
    assert "no GitHub installation" in reason
    assert "acme/widgets" in reason

    detail = await get_trigger_endpoint("tr-dead")
    assert detail.unable_to_fire_reason == reason
    assert (await get_trigger_endpoint("tr-live")).unable_to_fire_reason is None


async def test_a_whitespace_installation_id_is_as_absent_as_an_empty_one() -> None:
    """The poller strips it before deciding (ISS-542), so the read path must too."""
    await _store("tr-blank", "acme/widgets", "   ")

    assert (await _listed())["tr-blank"] is not None


async def test_a_rule_without_a_repository_is_not_flagged() -> None:
    """A repository-less rule needs no installation (see _resolve_installation_id)."""
    await _store("tr-norepo", "", "")

    assert (await _listed())["tr-norepo"] is None
    assert (await get_trigger_endpoint("tr-norepo")).unable_to_fire_reason is None
