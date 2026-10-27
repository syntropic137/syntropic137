"""A keyed start derives one execution id and knows a retry from a reuse (#2129).

A retry always compares against the request as the store rehydrates it, so
every `same_request` case here is asked of a stored-and-reloaded aggregate.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import pytest
from event_sourcing import EventStoreRepository
from event_sourcing.client.memory import MemoryEventStoreClient

from syn_adapters.storage.repositories import RepositoryAdapter
from syn_domain.contexts._shared.repository_ref import RepositoryRef
from syn_domain.contexts.orchestration._shared.eval_choice import (
    EvalChoice,
    EvalSelection,
    LaunchEval,
)
from syn_domain.contexts.orchestration._shared.tags import TagSet
from syn_domain.contexts.orchestration.domain.aggregate_eval.value_objects import EvalId
from syn_domain.contexts.orchestration.domain.aggregate_execution_request import (
    ExecutionRequestAggregate,
    execution_id_for_key,
    execution_request_id,
)
from syn_domain.contexts.orchestration.domain.commands.RequestExecutionCommand import (
    RequestExecutionCommand,
)

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

WORKFLOW_ID = "wf-2129"
REPO = RepositoryRef.from_slug("acme/widgets")


class TestTheKeyedId:
    def test_one_key_is_one_id_on_every_call(self) -> None:
        assert execution_id_for_key(WORKFLOW_ID, "trial:b1/1") == execution_id_for_key(
            WORKFLOW_ID, "trial:b1/1"
        )

    def test_it_keeps_128_digest_bits(self) -> None:
        # 48 bits fell to a chosen-key collision in ~2^24 hashes (codex #2155).
        derived = execution_id_for_key(WORKFLOW_ID, "trial:b1/1")
        assert derived.startswith("exec-")
        assert len(derived) == len("exec-") + 32
        int(derived.removeprefix("exec-"), 16)

    def test_two_keys_are_two_ids(self) -> None:
        assert execution_id_for_key(WORKFLOW_ID, "trial:b1/1") != execution_id_for_key(
            WORKFLOW_ID, "trial:b1/2"
        )

    def test_one_key_on_two_workflows_is_two_ids(self) -> None:
        assert execution_id_for_key("wf-a", "k") != execution_id_for_key("wf-b", "k")

    def test_the_workflow_and_key_cannot_trade_characters(self) -> None:
        assert execution_id_for_key("wf-a", "bk") != execution_id_for_key("wf-ab", "k")

    def test_an_empty_key_is_refused(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            execution_id_for_key(WORKFLOW_ID, "")


def _launch(selection: EvalSelection) -> LaunchEval:
    named = selection in (EvalSelection.EXPLICIT, EvalSelection.WORKFLOW_DEFAULT)
    return LaunchEval(EvalId("eval-2129") if named else None, selection)


async def _stored(launch: LaunchEval) -> ExecutionRequestAggregate:
    execution_id = execution_id_for_key(WORKFLOW_ID, "trial:b1/1")
    repo = RepositoryAdapter(
        EventStoreRepository(
            MemoryEventStoreClient(),
            ExecutionRequestAggregate,  # type: ignore[arg-type]  # ESP SDK TEvent invariance
            "ExecutionRequest",
        )
    )
    request = ExecutionRequestAggregate()
    request.request(
        RequestExecutionCommand(
            execution_id=execution_id,
            workflow_id=WORKFLOW_ID,
            inputs={"depth": "2"},
            task="do it",
            repos=[REPO],
            tags=TagSet(["trial:b1/1", "team-a"]),
            idempotency_key="trial:b1/1",
            launch_eval=launch,
        )
    )
    await repo.save_new(request)
    loaded = await repo.get_by_id(execution_request_id(execution_id))
    assert loaded is not None
    return loaded


@dataclass(frozen=True)
class _Ask:
    """What a retry asks for; the default is exactly what `_stored` recorded."""

    idempotency_key: str = "trial:b1/1"
    workflow_id: str = WORKFLOW_ID
    inputs: tuple[tuple[str, str], ...] = (("depth", "2"),)
    task: str | None = "do it"
    repos: tuple[RepositoryRef, ...] = (REPO,)
    tags: TagSet = field(default_factory=lambda: TagSet(["team-a", "trial:b1/1"]))
    choice: EvalChoice = field(default_factory=EvalChoice)

    def of(self, stored: ExecutionRequestAggregate) -> bool:
        return stored.same_request(
            idempotency_key=self.idempotency_key,
            workflow_id=self.workflow_id,
            inputs=dict(self.inputs),
            task=self.task,
            repos=list(self.repos),
            tags=self.tags,
            choice=self.choice,
        )


class TestARetryIsTheSameRequest:
    async def test_the_same_request_is_a_retry(self) -> None:
        stored = await _stored(_launch(EvalSelection.NONE))
        assert _Ask().of(stored)

    async def test_tags_are_compared_normalised(self) -> None:
        stored = await _stored(_launch(EvalSelection.NONE))
        assert replace(_Ask(), tags=TagSet([" Team-A", "trial:b1/1"])).of(stored)

    @pytest.mark.parametrize(
        "ask",
        [
            pytest.param(replace(_Ask(), idempotency_key="trial:b1/2"), id="key"),
            pytest.param(replace(_Ask(), workflow_id="wf-other"), id="workflow"),
            pytest.param(replace(_Ask(), inputs=(("depth", "3"),)), id="input-value"),
            pytest.param(replace(_Ask(), inputs=()), id="inputs-dropped"),
            pytest.param(replace(_Ask(), task="do something else"), id="task"),
            pytest.param(replace(_Ask(), task=None), id="task-dropped"),
            pytest.param(replace(_Ask(), repos=()), id="repos-dropped"),
            pytest.param(
                replace(_Ask(), repos=(RepositoryRef.from_slug("acme/gadgets"),)), id="repo"
            ),
            pytest.param(replace(_Ask(), tags=TagSet(["team-a"])), id="tags"),
            pytest.param(replace(_Ask(), choice=EvalChoice(ordinary=True)), id="ordinary"),
            pytest.param(
                replace(_Ask(), choice=EvalChoice(eval_id=EvalId("eval-2129"))), id="named-eval"
            ),
        ],
    )
    async def test_any_difference_is_a_reused_key(self, ask: _Ask) -> None:
        stored = await _stored(_launch(EvalSelection.NONE))
        assert not ask.of(stored)


class TestTheEvalIsComparedAsChosen:
    async def test_a_named_eval_matches_only_itself(self) -> None:
        stored = await _stored(_launch(EvalSelection.EXPLICIT))
        assert replace(_Ask(), choice=EvalChoice(eval_id=EvalId("eval-2129"))).of(stored)
        assert not replace(_Ask(), choice=EvalChoice(eval_id=EvalId("eval-other"))).of(stored)
        assert not replace(_Ask(), choice=EvalChoice()).of(stored)

    async def test_a_default_taken_is_a_launch_that_named_none(self) -> None:
        stored = await _stored(_launch(EvalSelection.WORKFLOW_DEFAULT))
        assert replace(_Ask(), choice=EvalChoice()).of(stored)
        assert not replace(_Ask(), choice=EvalChoice(eval_id=EvalId("eval-2129"))).of(stored)

    async def test_an_ordinary_run_matches_only_an_ordinary_retry(self) -> None:
        stored = await _stored(_launch(EvalSelection.ORDINARY))
        assert replace(_Ask(), choice=EvalChoice(ordinary=True)).of(stored)
        assert not replace(_Ask(), choice=EvalChoice()).of(stored)
