"""Tests for the system-wide contributor guard (#580), exercised through the handler."""

from __future__ import annotations

import pytest

from syn_domain.contexts.github._shared.trigger_query_store import (
    InMemoryTriggerQueryStore,
)
from syn_domain.contexts.github.domain.aggregate_trigger.TriggerRuleAggregate import (
    TriggerRuleAggregate,
)
from syn_domain.contexts.github.domain.commands.RegisterTriggerCommand import (
    RegisterTriggerCommand,
)
from syn_domain.contexts.github.domain.events.TriggerBlockedEvent import TriggerBlockedEvent
from syn_domain.contexts.github.slices.evaluate_webhook.contributor_guard import (
    ContributorGuardMode,
    ContributorPolicy,
    contributor_of,
)
from syn_domain.contexts.github.slices.evaluate_webhook.EvaluateWebhookHandler import (
    EvaluateWebhookHandler,
    TriggerBlockedResult,
    TriggerMatchResult,
)

pytestmark = pytest.mark.unit

TRUSTED = ContributorPolicy(mode=ContributorGuardMode.TRUSTED)


class SingleAggregateRepository:
    """Hands back one aggregate so recorded blocks can be inspected."""

    def __init__(self, aggregate: TriggerRuleAggregate) -> None:
        self.aggregate = aggregate

    async def get_by_id(self, id: str) -> TriggerRuleAggregate | None:
        return self.aggregate if id == self.aggregate.trigger_id else None

    async def save(self, aggregate: TriggerRuleAggregate) -> None:
        pass


async def _handler(
    event: str,
    policy: ContributorPolicy | None,
    conditions: tuple[dict[str, str], ...] = (),
) -> tuple[EvaluateWebhookHandler, TriggerRuleAggregate]:
    store = InMemoryTriggerQueryStore()
    agg = TriggerRuleAggregate()
    agg.register(
        RegisterTriggerCommand(
            name="guarded",
            event=event,
            conditions=conditions,
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
        conditions=[
            {"field": c.field, "operator": c.operator, "value": c.value} for c in agg.conditions
        ],
        input_mapping=agg.input_mapping,
        config=agg.config,
        installation_id=agg.installation_id,
        created_by=agg.created_by,
        status=agg.status.value,
    )
    agg.mark_events_as_committed()
    handler = EvaluateWebhookHandler(
        store=store,
        repository=SingleAggregateRepository(agg),
        contributor_policy=policy,
    )
    return handler, agg


def _pr_payload(login: str, association: str, number: int = 7):
    return {
        "action": "opened",
        "number": number,
        "sender": {"login": login, "type": "User"},
        "pull_request": {
            "number": number,
            "user": {"login": login},
            "author_association": association,
        },
    }


@pytest.mark.asyncio
async def test_untrusted_contributor_does_not_fire_and_block_is_recorded() -> None:
    handler, agg = await _handler("pull_request.opened", TRUSTED)

    results = await handler.evaluate(
        event="pull_request.opened",
        repository="org/repo",
        installation_id="inst-1",
        payload=_pr_payload("drive-by", "FIRST_TIME_CONTRIBUTOR"),
    )

    assert len(results) == 1
    assert isinstance(results[0], TriggerBlockedResult)
    assert results[0].guard_name == "contributor_guard"
    assert "drive-by" in results[0].reason
    blocked = [e.event for e in agg.get_uncommitted_events()]
    assert len(blocked) == 1
    assert isinstance(blocked[0], TriggerBlockedEvent)
    assert blocked[0].guard_name == "contributor_guard"
    assert blocked[0].payload_summary["sender"] == "drive-by"


@pytest.mark.asyncio
@pytest.mark.parametrize("association", ["OWNER", "MEMBER", "COLLABORATOR"])
async def test_trusted_contributor_fires(association: str) -> None:
    handler, _ = await _handler("pull_request.opened", TRUSTED)

    results = await handler.evaluate(
        event="pull_request.opened",
        repository="org/repo",
        installation_id="inst-1",
        payload=_pr_payload("maint", association),
    )

    assert len(results) == 1
    assert isinstance(results[0], TriggerMatchResult)


@pytest.mark.asyncio
async def test_pr_author_is_judged_not_the_sender() -> None:
    """A maintainer pushing to an external PR does not make its code trusted."""
    policy = ContributorPolicy(
        mode=ContributorGuardMode.TRUSTED, allowed_logins=frozenset({"maintainer"})
    )
    handler, _ = await _handler("pull_request.synchronize", policy)
    payload = _pr_payload("outsider", "NONE")
    payload["sender"] = {"login": "maintainer", "type": "User"}

    results = await handler.evaluate(
        event="pull_request.synchronize",
        repository="org/repo",
        installation_id="inst-1",
        payload=payload,
    )

    assert isinstance(results[0], TriggerBlockedResult)
    assert results[0].guard_name == "contributor_guard"


@pytest.mark.asyncio
async def test_default_policy_lets_an_untrusted_contributor_fire() -> None:
    """No policy configured: behaviour before #580 is unchanged."""
    handler, _ = await _handler("pull_request.opened", None)

    results = await handler.evaluate(
        event="pull_request.opened",
        repository="org/repo",
        installation_id="inst-1",
        payload=_pr_payload("drive-by", "NONE"),
    )

    assert isinstance(results[0], TriggerMatchResult)


@pytest.mark.asyncio
async def test_allowlisted_login_fires_and_others_do_not() -> None:
    policy = ContributorPolicy(
        mode=ContributorGuardMode.ALLOWLIST, allowed_logins=frozenset({"Alice"})
    )
    handler, _ = await _handler("pull_request.opened", policy)

    allowed = await handler.evaluate(
        event="pull_request.opened",
        repository="org/repo",
        installation_id="inst-1",
        payload=_pr_payload("alice", "NONE", 1),
    )
    # OWNER is not enough under allowlist: only the list counts.
    refused = await handler.evaluate(
        event="pull_request.opened",
        repository="org/repo",
        installation_id="inst-1",
        payload=_pr_payload("owner", "OWNER", 2),
    )

    assert isinstance(allowed[0], TriggerMatchResult)
    assert isinstance(refused[0], TriggerBlockedResult)
    assert refused[0].guard_name == "contributor_guard"


@pytest.mark.asyncio
async def test_guard_runs_before_per_trigger_conditions() -> None:
    handler, _ = await _handler(
        "pull_request.opened",
        TRUSTED,
        conditions=({"field": "pull_request.draft", "operator": "eq", "value": "true"},),
    )

    results = await handler.evaluate(
        event="pull_request.opened",
        repository="org/repo",
        installation_id="inst-1",
        payload=_pr_payload("drive-by", "NONE"),
    )

    assert isinstance(results[0], TriggerBlockedResult)
    assert results[0].guard_name == "contributor_guard"


@pytest.mark.asyncio
async def test_ci_bot_gets_no_blanket_pass_under_a_restrictive_mode() -> None:
    """github-actions[bot] sends check_run for external PRs; it must not slip through."""
    handler, _ = await _handler("check_run.completed", TRUSTED)
    payload = {
        "sender": {"login": "github-actions[bot]", "type": "Bot"},
        "check_run": {"conclusion": "failure", "pull_requests": [{"number": 3}]},
    }

    results = await handler.evaluate(
        event="check_run.completed",
        repository="org/repo",
        installation_id="inst-1",
        payload=payload,
    )

    assert isinstance(results[0], TriggerBlockedResult)
    assert results[0].guard_name == "contributor_guard"


@pytest.mark.asyncio
async def test_allowlisted_bot_fires_under_trusted_mode() -> None:
    policy = ContributorPolicy(
        mode=ContributorGuardMode.TRUSTED, allowed_logins=frozenset({"syn-engineer[bot]"})
    )
    handler, _ = await _handler("check_run.completed", policy)
    payload = {
        "sender": {"login": "syn-engineer[bot]", "type": "Bot"},
        "check_run": {"conclusion": "failure", "pull_requests": [{"number": 4}]},
    }

    results = await handler.evaluate(
        event="check_run.completed",
        repository="org/repo",
        installation_id="inst-1",
        payload=payload,
    )

    assert isinstance(results[0], TriggerMatchResult)


def test_comment_author_is_judged_on_an_issue_comment() -> None:
    payload = {
        "sender": {"login": "maint"},
        "issue": {"user": {"login": "outsider"}, "author_association": "NONE"},
        "comment": {"user": {"login": "maint"}, "author_association": "MEMBER"},
    }

    contributor = contributor_of(payload)

    assert (contributor.login, contributor.association) == ("maint", "MEMBER")


def test_unparseable_payload_is_refused_under_a_restrictive_mode() -> None:
    assert TRUSTED.refusal({"pull_request": "not-an-object"}) is not None
