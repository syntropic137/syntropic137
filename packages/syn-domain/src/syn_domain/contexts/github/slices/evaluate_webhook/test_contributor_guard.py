"""Tests for the system-wide contributor guard (#580), exercised through the handler."""

from __future__ import annotations

from typing import TYPE_CHECKING

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
from syn_domain.contexts.github.slices.event_pipeline.event_type_mapper import (
    map_events_api_to_normalized,
)

if TYPE_CHECKING:
    from syn_domain.contexts.github.slices.event_pipeline.normalized_event import (
        NormalizedEvent,
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


# Events API items as GitHub returns them (ids from syntropic137/syntropic137,
# repo renamed to the fixture trigger's). Polled events carry ``actor``, not
# ``sender``, and a polled review omits ``author_association``.
def _polled_push(actor: str):
    return {
        "id": "26384613026",
        "type": "PushEvent",
        "actor": {"id": 129192050, "login": actor, "display_login": actor},
        "repo": {"id": 1107456800, "name": "org/repo"},
        "payload": {
            "repository_id": 1107456800,
            "push_id": 49289079368,
            "ref": "refs/heads/main",
            "head": "4f9daea474688b8f739cf0e3e8eb1cd7f5d5cbd6",
            "before": "95f415edf4955a4caba85cc405b3bd3a99364b4a",
        },
        "public": True,
        "created_at": "2026-11-06T19:33:49Z",
    }


def _polled_review(reviewer: str, pr_author: str | None = None, pr_association: str = ""):
    pull_request = {"id": 1, "number": 2184, "head": {}, "base": {}}
    if pr_author is not None:
        pull_request = {
            **pull_request,
            "user": {"login": pr_author},
            "author_association": pr_association,
        }
    return {
        "id": "19394439086",
        "type": "PullRequestReviewEvent",
        "actor": {"id": 198982749, "login": reviewer, "display_login": reviewer},
        "repo": {"id": 1107456800, "name": "org/repo"},
        "payload": {
            "action": "created",
            "review": {
                "id": 5809164794,
                "user": {"login": reviewer, "type": "Bot"},
                "state": "commented",
            },
            "pull_request": pull_request,
        },
        "public": True,
        "created_at": "2026-11-07T01:22:44Z",
    }


def _mapped(raw) -> NormalizedEvent:
    """Run a raw Events API item through the production mapper, as the poller does."""
    normalized = map_events_api_to_normalized(raw, "inst-1")
    assert normalized is not None
    return normalized


async def _evaluate_polled(
    normalized: NormalizedEvent, policy: ContributorPolicy
) -> tuple[TriggerMatchResult | TriggerBlockedResult, TriggerRuleAggregate]:
    event = f"{normalized.event_type}.{normalized.action}".rstrip(".")
    handler, agg = await _handler(event, policy)
    results = await handler.evaluate(
        event=event,
        repository=normalized.repository,
        installation_id="inst-1",
        payload=normalized.payload,
    )
    result = results[0]
    assert isinstance(result, TriggerMatchResult | TriggerBlockedResult)
    return result, agg


@pytest.mark.asyncio
async def test_polled_push_is_judged_on_its_events_api_actor() -> None:
    policy = ContributorPolicy(
        mode=ContributorGuardMode.ALLOWLIST, allowed_logins=frozenset({"NeuralEmpowerment"})
    )

    allowed, _ = await _evaluate_polled(_mapped(_polled_push("NeuralEmpowerment")), policy)
    refused, agg = await _evaluate_polled(_mapped(_polled_push("outsider")), policy)

    assert isinstance(allowed, TriggerMatchResult)
    assert isinstance(refused, TriggerBlockedResult)
    assert "outsider" in refused.reason
    blocked = [e.event for e in agg.get_uncommitted_events()]
    assert isinstance(blocked[0], TriggerBlockedEvent)
    assert "outsider" in blocked[0].reason


def test_events_api_actor_is_not_exposed_as_sender() -> None:
    """Per-trigger ``sender.*`` conditions see a polled payload as they did before #580."""
    normalized = _mapped(_polled_push("NeuralEmpowerment"))
    assert "sender" not in normalized.payload


@pytest.mark.asyncio
async def test_polled_review_without_association_is_judged_on_its_author() -> None:
    policy = ContributorPolicy(
        mode=ContributorGuardMode.ALLOWLIST, allowed_logins=frozenset({"Copilot"})
    )

    allowed, _ = await _evaluate_polled(_mapped(_polled_review("Copilot")), policy)
    refused, _ = await _evaluate_polled(_mapped(_polled_review("outsider")), policy)

    assert isinstance(allowed, TriggerMatchResult)
    assert isinstance(refused, TriggerBlockedResult)
    assert "outsider" in refused.reason


def test_review_author_outranks_a_distinct_sender_without_association() -> None:
    normalized = _mapped(_polled_review("Copilot"))
    payload = {**normalized.payload, "sender": {"login": "unlisted-editor"}}
    policy = ContributorPolicy(
        mode=ContributorGuardMode.ALLOWLIST, allowed_logins=frozenset({"Copilot"})
    )

    assert policy.refusal(payload) is None


@pytest.mark.asyncio
async def test_unclassified_review_does_not_inherit_the_pr_authors_trust() -> None:
    raw = _polled_review("outsider", pr_author="maintainer", pr_association="OWNER")

    refused, _ = await _evaluate_polled(_mapped(raw), TRUSTED)

    assert isinstance(refused, TriggerBlockedResult)
    assert "outsider" in refused.reason
