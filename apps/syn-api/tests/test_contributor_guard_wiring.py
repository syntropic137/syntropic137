"""The contributor guard setting reaches every trigger evaluation path (#580)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from syn_api import _wiring
from syn_api.routes.webhooks.handlers import _evaluate_triggers
from syn_domain.contexts.github import (
    ContributorGuardMode,
    EventSource,
    InMemoryTriggerQueryStore,
    NormalizedEvent,
)
from syn_domain.contexts.github.domain.aggregate_trigger.TriggerRuleAggregate import (
    TriggerRuleAggregate,
)
from syn_domain.contexts.github.domain.commands.RegisterTriggerCommand import (
    RegisterTriggerCommand,
)
from syn_shared.settings.trigger_contributors import TriggerContributorSettings

pytestmark = pytest.mark.unit


class NullRepository:
    async def get_by_id(self, id: str) -> None:
        return None

    async def save(self, aggregate: TriggerRuleAggregate) -> None:
        pass


async def _store_with_pr_trigger() -> tuple[InMemoryTriggerQueryStore, str]:
    store = InMemoryTriggerQueryStore()
    agg = TriggerRuleAggregate()
    agg.register(
        RegisterTriggerCommand(
            name="pr-review",
            event="pull_request.opened",
            repository="org/repo",
            workflow_id="wf",
        )
    )
    await store.index_trigger(
        trigger_id=agg.trigger_id,
        name=agg.name,
        event=agg.event,
        repository=agg.repository,
        workflow_id=agg.workflow_id,
        conditions=[],
        input_mapping=agg.input_mapping,
        config=agg.config,
        installation_id=agg.installation_id,
        created_by=agg.created_by,
        status=agg.status.value,
    )
    return store, agg.trigger_id


def _external_pr(number: int):
    return {
        "action": "opened",
        "number": number,
        "repository": {"full_name": "org/repo"},
        "sender": {"login": "drive-by"},
        "pull_request": {
            "number": number,
            "user": {"login": "drive-by"},
            "author_association": "NONE",
        },
    }


def test_settings_default_to_allow_all(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SYN_TRIGGER_CONTRIBUTOR_MODE", raising=False)
    monkeypatch.delenv("SYN_TRIGGER_CONTRIBUTOR_ALLOWED_LOGINS", raising=False)

    assert _wiring.get_contributor_policy().mode is ContributorGuardMode.ALLOW_ALL


def test_allowlist_setting_is_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYN_TRIGGER_CONTRIBUTOR_MODE", "allowlist")
    monkeypatch.setenv("SYN_TRIGGER_CONTRIBUTOR_ALLOWED_LOGINS", " alice , syn-engineer[bot] ,")

    policy = _wiring.get_contributor_policy()

    assert policy.mode is ContributorGuardMode.ALLOWLIST
    assert policy.allowed_logins == frozenset({"alice", "syn-engineer[bot]"})


def test_allowlist_without_logins_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYN_TRIGGER_CONTRIBUTOR_MODE", "allowlist")
    monkeypatch.setenv("SYN_TRIGGER_CONTRIBUTOR_ALLOWED_LOGINS", "")

    with pytest.raises(ValueError, match="ALLOWED_LOGINS"):
        TriggerContributorSettings()


@pytest.mark.anyio
@pytest.mark.parametrize(("mode", "fires"), [("allow_all", True), ("trusted", False)])
async def test_webhook_route_applies_configured_mode(
    monkeypatch: pytest.MonkeyPatch, mode: str, fires: bool
) -> None:
    monkeypatch.setenv("SYN_TRIGGER_CONTRIBUTOR_MODE", mode)
    store, trigger_id = await _store_with_pr_trigger()

    with (
        patch("syn_api.routes.webhooks.handlers.get_trigger_store", return_value=store),
        patch("syn_api.routes.webhooks.handlers.get_trigger_repo", return_value=NullRepository()),
    ):
        fired, _ = await _evaluate_triggers("pull_request", "opened", _external_pr(1), "inst-1")

    assert fired == ([trigger_id] if fires else [])


@pytest.mark.anyio
@pytest.mark.parametrize(("mode", "fire_count"), [("allow_all", 1), ("trusted", 0)])
async def test_event_pipeline_applies_configured_mode(
    monkeypatch: pytest.MonkeyPatch, mode: str, fire_count: int
) -> None:
    """The polling / pipeline path builds its own handler and must not bypass the guard."""
    monkeypatch.setenv("SYN_TRIGGER_CONTRIBUTOR_MODE", mode)
    monkeypatch.setattr(_wiring, "_event_pipeline_singleton", None)
    store, trigger_id = await _store_with_pr_trigger()
    monkeypatch.setattr(_wiring, "get_trigger_store", lambda: store)
    monkeypatch.setattr(_wiring, "get_trigger_repo", NullRepository)

    pipeline = _wiring.get_event_pipeline()
    await pipeline.ingest(
        NormalizedEvent(
            event_type="pull_request",
            action="opened",
            repository="org/repo",
            installation_id="inst-1",
            dedup_key="pr:org/repo:2:opened",
            source=EventSource.EVENTS_API,
            payload=_external_pr(2),
            received_at=datetime.now(UTC),
        )
    )

    assert await store.get_fire_count(trigger_id=trigger_id, pr_number=2) == fire_count
