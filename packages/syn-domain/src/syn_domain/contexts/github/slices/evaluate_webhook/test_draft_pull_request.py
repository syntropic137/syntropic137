"""A check_run trigger is held back while its pull request is a draft (#2058).

A draft PR is still owned by the workflow that opened it, which handles its own
CI. The ``self-healing`` preset firing on it put a second agent on the branch.
A ``check_run`` payload carries no draft flag, so the evaluator asks a
``PullRequestDraftPort``; these tests drive the real preset through the handler
with a double for that port and observe dispatch through ``on_fire``.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from syn_domain.contexts.github._shared.trigger_evaluation_types import (
    TriggerBlockedResult,
    TriggerMatchResult,
)
from syn_domain.contexts.github._shared.trigger_presets import create_preset_command
from syn_domain.contexts.github._shared.trigger_query_store import InMemoryTriggerQueryStore
from syn_domain.contexts.github.domain.aggregate_trigger.TriggerRuleAggregate import (
    TriggerRuleAggregate,
)
from syn_domain.contexts.github.ports import (
    PullRequestDraftReading,
    PullRequestReadiness,
)
from syn_domain.contexts.github.slices.evaluate_webhook.debouncer import TriggerDebouncer
from syn_domain.contexts.github.slices.evaluate_webhook.EvaluateWebhookHandler import (
    EvaluateWebhookHandler,
)

pytestmark = pytest.mark.unit

_REPO = "acme/widgets"
_PR = 42
_HEAD_SHA = "2058a2058a2058a2058a2058a2058a2058a2058a"


class _DraftState:
    """``PullRequestDraftPort`` double: answers whatever the test sets."""

    def __init__(self, reading: PullRequestDraftReading) -> None:
        self.reading = reading
        self.asked: list[tuple[str, int, str]] = []

    async def read_draft_state(
        self, repository: str, pr_number: int, installation_id: str
    ) -> PullRequestDraftReading:
        self.asked.append((repository, pr_number, installation_id))
        return self.reading


_DRAFT = PullRequestDraftReading(readiness=PullRequestReadiness.DRAFT)
_READY = PullRequestReadiness.READY


class _NullRepository:
    async def get_by_id(self, id: str) -> None:
        del id

    async def save(self, aggregate: object) -> None:
        del aggregate


class _Dispatches:
    """Stands in for dispatch: every fire the handler hands on."""

    def __init__(self) -> None:
        self.fired: list[TriggerMatchResult] = []

    async def __call__(self, result: TriggerMatchResult, payload: object) -> None:
        del payload
        self.fired.append(result)


async def _self_healing_store() -> InMemoryTriggerQueryStore:
    store = InMemoryTriggerQueryStore()
    aggregate = TriggerRuleAggregate()
    aggregate.register(create_preset_command("self-healing", _REPO, installation_id="inst-1"))
    await store.index_trigger(
        trigger_id=aggregate.trigger_id,
        name=aggregate.name,
        event=aggregate.event,
        repository=aggregate.repository,
        workflow_id=aggregate.workflow_id,
        conditions=[
            {"field": c.field, "operator": c.operator, "value": c.value}
            for c in aggregate.conditions
        ],
        input_mapping=aggregate.input_mapping,
        config=aggregate.config,
        installation_id=aggregate.installation_id,
        created_by=aggregate.created_by,
        status=aggregate.status.value,
    )
    return store


def _failed_check(check_id: int = 1, *, on_a_pr: bool = True):
    pull_requests = [{"number": _PR, "head": {"ref": "feat/x", "sha": _HEAD_SHA}}]
    return {
        "repository": {"full_name": _REPO},
        "check_run": {
            "id": check_id,
            "name": f"lint-{check_id}",
            "conclusion": "failure",
            "head_sha": _HEAD_SHA,
            "pull_requests": pull_requests if on_a_pr else [],
        },
        "_delivery_id": f"delivery-{check_id}",
    }


def _handler(
    store: InMemoryTriggerQueryStore,
    draft_state: _DraftState,
    dispatches: _Dispatches,
    debouncer: TriggerDebouncer | None = None,
) -> EvaluateWebhookHandler:
    return EvaluateWebhookHandler(
        store=store,
        repository=_NullRepository(),
        debouncer=debouncer,
        on_fire=dispatches,
        draft_reader=draft_state,
    )


async def _evaluate(
    handler: EvaluateWebhookHandler, check_id: int = 1, *, on_a_pr: bool = True
) -> list[object]:
    return list(
        await handler.evaluate(
            event="check_run.completed",
            repository=_REPO,
            installation_id="inst-1",
            payload=_failed_check(check_id, on_a_pr=on_a_pr),
        )
    )


async def test_a_failed_check_on_a_draft_pr_does_not_dispatch() -> None:
    store, dispatches = await _self_healing_store(), _Dispatches()
    draft_state = _DraftState(_DRAFT)

    [result] = await _evaluate(_handler(store, draft_state, dispatches))

    assert dispatches.fired == []
    assert isinstance(result, TriggerBlockedResult)
    assert result.guard_name == "draft_pull_request"
    assert draft_state.asked == [(_REPO, _PR, "inst-1")]


async def test_the_same_check_dispatches_once_the_pr_is_ready() -> None:
    store, dispatches = await _self_healing_store(), _Dispatches()
    draft_state = _DraftState(_DRAFT)
    handler = _handler(store, draft_state, dispatches)
    await _evaluate(handler)

    draft_state.reading = PullRequestDraftReading(readiness=_READY)
    [result] = await _evaluate(handler)

    # The draft block spent neither the delivery nor an attempt.
    assert isinstance(result, TriggerMatchResult)
    assert len(dispatches.fired) == 1


async def test_an_unknown_draft_state_does_not_dispatch_and_says_why(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store, dispatches = await _self_healing_store(), _Dispatches()
    draft_state = _DraftState(
        PullRequestDraftReading(
            readiness=PullRequestReadiness.UNKNOWN, detail="GitHubAppError: 502 Bad Gateway"
        )
    )

    with caplog.at_level(logging.INFO):
        [result] = await _evaluate(_handler(store, draft_state, dispatches))

    assert dispatches.fired == []
    assert isinstance(result, TriggerBlockedResult)
    assert result.guard_name == "draft_state_unknown"
    assert "502 Bad Gateway" in result.reason
    assert "502 Bad Gateway" in caplog.text


async def test_two_failed_checks_on_one_head_sha_dispatch_once() -> None:
    # Two checks of the same push fail at once. The existing per-(trigger, PR)
    # concurrency guard holds the second while the first self-heal runs.
    store, dispatches = await _self_healing_store(), _Dispatches()
    handler = _handler(store, _DraftState(PullRequestDraftReading(readiness=_READY)), dispatches)

    first, second = await asyncio.gather(
        _evaluate(handler, check_id=1),
        _evaluate(handler, check_id=2),
    )

    assert len(dispatches.fired) == 1
    blocked = [r for r in (*first, *second) if isinstance(r, TriggerBlockedResult)]
    assert [b.guard_name for b in blocked] == ["concurrency"]


async def test_a_ready_pr_dispatches_as_before() -> None:
    store, dispatches = await _self_healing_store(), _Dispatches()
    draft_state = _DraftState(PullRequestDraftReading(readiness=_READY))

    [result] = await _evaluate(_handler(store, draft_state, dispatches))

    assert isinstance(result, TriggerMatchResult)
    assert [f.execution_id for f in dispatches.fired] == [result.execution_id]


async def test_a_check_with_no_pull_request_is_not_looked_up() -> None:
    store, dispatches = await _self_healing_store(), _Dispatches()
    draft_state = _DraftState(_DRAFT)
    await _evaluate(_handler(store, draft_state, dispatches), on_a_pr=False)

    assert draft_state.asked == []


async def test_a_deferred_retry_still_checks_the_draft_state() -> None:
    # The retry builds a fresh handler; it must carry the reader with it, or a
    # PR turned back into a draft during a cooldown would be self-healed.
    store, dispatches = await _self_healing_store(), _Dispatches()
    draft_state = _DraftState(_DRAFT)
    debouncer = TriggerDebouncer()
    handler = _handler(store, draft_state, dispatches, debouncer=debouncer)
    [rule] = await store.list_by_event_and_repo("check_run.completed", _REPO)

    await handler._schedule_deferred(  # pyright: ignore[reportPrivateUsage]
        rule=rule,
        event="check_run.completed",
        repository=_REPO,
        installation_id="inst-1",
        payload=_failed_check(),
        delay=0.01,
        reason="cooldown",
        key_suffix=":retry",
    )
    await asyncio.sleep(0.1)

    assert draft_state.asked == [(_REPO, _PR, "inst-1")]
    assert dispatches.fired == []
