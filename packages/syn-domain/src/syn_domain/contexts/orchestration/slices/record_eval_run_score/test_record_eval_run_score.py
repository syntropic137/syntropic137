"""Scoring a run of an eval, end to end through the real handler and projection (Evals v2).

The stream is written by the real aggregates through real repositories; the
read side is replayed off that stream through ``handle_event``, the path the
coordinator uses, twice, so an appending handler would show up.
"""

from __future__ import annotations

import os
from dataclasses import replace
from decimal import Decimal

os.environ.setdefault("APP_ENVIRONMENT", "test")

import pytest
from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.orchestration.domain.aggregate_eval import (
    EvalRunNotMemberError,
    Verdict,
)
from syn_domain.contexts.orchestration.domain.commands.RecordEvalRunScoreCommand import (
    RecordEvalRunScoreCommand,
)
from syn_domain.contexts.orchestration.domain.read_models.eval_runs import (
    EvalRunFacts,
    EvalRunScore,
    EvalRunStats,
    PhaseModel,
    summarize,
)
from syn_domain.contexts.orchestration.slices.list_evals.projection import EvalListProjection
from syn_domain.contexts.orchestration.slices.list_evals.test_list_evals import (
    _EVAL,
    _OTHER,
    _Stream,
)
from syn_domain.contexts.orchestration.slices.record_eval_run_score import (
    RecordEvalRunScoreHandler,
)
from syn_domain.testing.stored_replay import replay

pytestmark = pytest.mark.unit


def _score(
    execution_id: str, verdict: Verdict, *, eval_id: str = str(_EVAL)
) -> RecordEvalRunScoreCommand:
    return RecordEvalRunScoreCommand(
        eval_id=_EVAL if eval_id == str(_EVAL) else _OTHER,
        execution_id=execution_id,
        verdict=verdict,
        score=0.5 if verdict is Verdict.FAIL else 1.0,
        evidence=f"**{verdict}** for {execution_id}",
        scorer="eval_suite.py",
        scorer_version="2",
    )


async def _scored_stream() -> tuple[_Stream, RecordEvalRunScoreHandler]:
    stream = _Stream()
    await stream.create_eval(_EVAL, "Refactor quality", ["suite:verifier-seed"])
    await stream.create_eval(_OTHER, "Other", [])
    await stream.on_eval(_EVAL, "freeze")
    await stream.launch("run-a", _EVAL, [])
    await stream.launch("run-b", None, [])
    await stream.attach("run-b", _EVAL)
    await stream.launch("run-outside", None, [])
    handler = RecordEvalRunScoreHandler(stream.evals, stream.executions)
    return stream, handler


async def _replayed(stream: _Stream, *, times: int) -> EvalListProjection:
    evals = EvalListProjection(InMemoryProjectionStore())
    for _ in range(times):
        await replay(stream.client, MemoryCheckpointStore(), evals)
    return evals


class TestRecordEvalRunScore:
    async def test_rescoring_replaces_the_current_score_and_keeps_history(self) -> None:
        stream, handler = await _scored_stream()

        first = await handler.handle(_score("run-a", Verdict.FAIL))
        second = await handler.handle(_score("run-a", Verdict.PASS))
        await handler.handle(_score("run-b", Verdict.ERROR))

        assert first is not None and first.success
        assert second is not None and second.success
        scores = await (await _replayed(stream, times=1)).scores(str(_EVAL))
        assert set(scores) == {"run-a", "run-b"}
        assert scores["run-a"].verdict is Verdict.PASS
        assert scores["run-a"].score == 1.0
        assert scores["run-a"].evidence == "**PASS** for run-a"
        assert scores["run-a"].scorer == "eval_suite.py"
        assert scores["run-a"].scorer_version == "2"
        assert scores["run-b"].verdict is Verdict.ERROR
        # Both verdicts on run-a are on the Eval stream, not only the latest.
        envelopes, _end, _next = await stream.client.read_all(max_count=1_000)
        scored = [e for e in envelopes if e.event.event_type == "EvalRunScored"]
        assert len(scored) == 3

    async def test_scoring_an_execution_that_is_not_a_member_is_refused(self) -> None:
        stream, handler = await _scored_stream()

        with pytest.raises(EvalRunNotMemberError):
            await handler.handle(_score("run-outside", Verdict.PASS))
        with pytest.raises(EvalRunNotMemberError):
            await handler.handle(_score("no-such-run", Verdict.PASS))
        # A member of _EVAL is not a member of _OTHER.
        with pytest.raises(EvalRunNotMemberError):
            await handler.handle(_score("run-a", Verdict.PASS, eval_id=str(_OTHER)))

        assert await (await _replayed(stream, times=1)).scores(str(_EVAL)) == {}

    async def test_a_detached_run_can_no_longer_be_scored(self) -> None:
        stream, handler = await _scored_stream()
        await stream.detach("run-b", _EVAL)

        with pytest.raises(EvalRunNotMemberError):
            await handler.handle(_score("run-b", Verdict.PASS))

    async def test_frozen_and_archived_evals_accept_scores(self) -> None:
        stream, handler = await _scored_stream()
        await stream.on_eval(_EVAL, "archive")

        result = await handler.handle(_score("run-a", Verdict.PASS))

        assert result is not None and result.success

    async def test_replay_rebuilds_identical_scores(self) -> None:
        stream, handler = await _scored_stream()
        await handler.handle(_score("run-a", Verdict.FAIL))
        await handler.handle(_score("run-a", Verdict.PASS))
        await handler.handle(_score("run-b", Verdict.FAIL))

        once = await (await _replayed(stream, times=1)).scores(str(_EVAL))
        thrice = await (await _replayed(stream, times=3)).scores(str(_EVAL))

        assert once == thrice
        assert len(once) == 2


def _run(
    execution_id: str,
    workflow_id: str,
    models: list[str],
    verdict: Verdict | None,
    cost: str | None,
    started_at: str,
    version: str | None = None,
    duration: float | None = None,
) -> EvalRunFacts:
    return EvalRunFacts(
        execution_id=execution_id,
        workflow_id=workflow_id,
        workflow_version=version,
        status="completed",
        started_at=started_at,
        completed_at=None,
        models=tuple(PhaseModel(f"p{i}", m) for i, m in enumerate(models)),
        total_cost_usd=None if cost is None else Decimal(cost),
        duration_seconds=duration,
        score=None
        if verdict is None
        else EvalRunScore(
            eval_id=str(_EVAL),
            execution_id=execution_id,
            verdict=verdict,
            scorer="t",
            scorer_version="1",
            scored_at=started_at,
        ),
    )


class TestSummarize:
    def test_two_workflows_by_two_models_group_into_four_variants(self) -> None:
        opus, sonnet = "claude-opus-5-5", "claude-sonnet-5"
        runs = [
            _run("1", "wf-a", [opus, opus], Verdict.PASS, "1.00", "2026-10-01T00:00:00+00:00"),
            _run("2", "wf-a", [opus], Verdict.FAIL, "3.00", "2026-10-02T00:00:00+00:00"),
            _run("3", "wf-a", [sonnet], Verdict.PASS, None, "2026-10-03T00:00:00+00:00"),
            _run("4", "wf-b", [opus], Verdict.ERROR, "2.00", "2026-10-04T00:00:00+00:00"),
            _run("5", "wf-b", [sonnet, opus], None, "4.00", "2026-10-05T00:00:00+00:00"),
            _run("6", "wf-b", [opus, sonnet], Verdict.PASS, "6.00", "2026-10-06T00:00:00+00:00"),
        ]

        summary = summarize(runs)

        assert summary.run_count == 6
        assert summary.scored_count == 5
        # Run 4's ERROR is scored but not judged: PASS over PASS + FAIL is 3/4.
        assert summary.pass_rate == pytest.approx(3 / 4)
        assert summary.last_run_at == "2026-10-06T00:00:00+00:00"
        assert summary.last_verdict is Verdict.PASS
        by_key = {(v.workflow_id, v.models): v for v in summary.variants}
        assert set(by_key) == {
            ("wf-a", (opus,)),
            ("wf-a", (sonnet,)),
            ("wf-b", (opus,)),
            ("wf-b", (opus, sonnet)),
        }
        wf_a_opus = by_key["wf-a", (opus,)]
        assert (wf_a_opus.run_count, wf_a_opus.pass_count) == (2, 1)
        assert wf_a_opus.pass_rate == pytest.approx(0.5)
        assert wf_a_opus.avg_cost_usd == Decimal("2.00")
        assert wf_a_opus.last_run_at == "2026-10-02T00:00:00+00:00"
        assert by_key["wf-a", (sonnet,)].avg_cost_usd is None
        # ERROR-only: nothing was judged, so no rate rather than 0%.
        assert by_key["wf-b", (opus,)].pass_rate is None
        mixed = by_key["wf-b", (opus, sonnet)]
        # Unscored run 5 counts as a run, not as a scored one.
        assert (mixed.run_count, mixed.pass_count, mixed.pass_rate) == (2, 1, 1.0)
        assert mixed.avg_cost_usd == Decimal("5.00")

    def test_two_versions_of_one_workflow_are_two_variants(self) -> None:
        opus = "claude-opus-5-5"
        runs = [
            _run("1", "wf-a", [opus], Verdict.PASS, "1.00", "2026-10-01T00:00:00+00:00", "1.0.0"),
            _run("2", "wf-a", [opus], Verdict.FAIL, "3.00", "2026-10-02T00:00:00+00:00", "2.0.0"),
            _run("3", "wf-a", [opus], Verdict.PASS, "2.00", "2026-10-03T00:00:00+00:00", "2.0.0"),
            _run("4", "wf-a", [opus], Verdict.FAIL, None, "2026-10-04T00:00:00+00:00"),
        ]

        summary = summarize(runs)

        by_version = {v.workflow_version: v for v in summary.variants}
        assert set(by_version) == {"1.0.0", "2.0.0", None}
        assert (by_version["1.0.0"].run_count, by_version["1.0.0"].pass_rate) == (1, 1.0)
        assert (by_version["2.0.0"].run_count, by_version["2.0.0"].pass_count) == (2, 1)
        assert by_version["2.0.0"].avg_cost_usd == Decimal("2.50")
        assert by_version[None].run_count == 1
        assert {v.models for v in summary.variants} == {(opus,)}

    def test_no_runs_has_no_rate(self) -> None:
        summary = summarize([])

        assert (summary.run_count, summary.pass_rate, summary.last_verdict) == (0, None, None)
        assert summary.variants == ()
        assert summary.stats == EvalRunStats(None, 0, None, 0, None)

    def test_duration_and_cost_are_medians_and_cost_per_pass_pays_for_every_run(self) -> None:
        opus = "claude-opus-5-5"
        runs = [
            _run("1", "wf-a", [opus], Verdict.PASS, "1.00", "2026-10-01T00:00:00+00:00", None, 60),
            _run("2", "wf-a", [opus], Verdict.FAIL, "3.00", "2026-10-02T00:00:00+00:00", None, 600),
            _run(
                "3", "wf-a", [opus], Verdict.ERROR, "2.00", "2026-10-03T00:00:00+00:00", None, 120
            ),
            _run("4", "wf-a", [opus], None, "6.00", "2026-10-04T00:00:00+00:00", None, 3000),
            _run("5", "wf-a", [opus], Verdict.PASS, None, "2026-10-05T00:00:00+00:00", None, None),
        ]

        [variant] = summarize(runs).variants

        # Even count of known durations (60, 120, 600, 3000): the mean of the middle two.
        assert variant.stats.median_duration_seconds == pytest.approx(360)
        assert variant.stats.median_cost_usd == Decimal("2.50")
        # 12.00 known spend - the FAIL, the ERROR and the unscored run included -
        # over 2 PASS runs. Run 5's cost is unknown, so this is a lower bound.
        assert variant.stats.cost_per_pass_usd == Decimal("6.00")
        assert variant.stats.incomplete_cost_count == 1
        assert variant.stats.incomplete_duration_count == 1
        assert variant.last_verdict is Verdict.PASS

    def test_nothing_passed_has_no_cost_per_pass_and_each_variant_its_own_last_verdict(
        self,
    ) -> None:
        opus, sonnet = "claude-opus-5-5", "claude-sonnet-5"
        runs = [
            _run("1", "wf-a", [opus], Verdict.FAIL, "1.00", "2026-10-01T00:00:00+00:00"),
            _run("2", "wf-a", [opus], Verdict.ERROR, "1.00", "2026-10-02T00:00:00+00:00"),
            _run("3", "wf-a", [sonnet], Verdict.PASS, "4.00", "2026-10-03T00:00:00+00:00"),
        ]

        summary = summarize(runs)

        by_models = {v.models: v for v in summary.variants}
        assert by_models[opus,].stats.cost_per_pass_usd is None
        assert by_models[opus,].last_verdict is Verdict.ERROR
        assert by_models[sonnet,].last_verdict is Verdict.PASS
        # Across the eval: 6.00 over one PASS.
        assert summary.stats.cost_per_pass_usd == Decimal("6.00")
        assert summary.stats.median_duration_seconds is None

    def test_a_lower_bound_is_spend_but_never_a_median(self) -> None:
        """A run with unpriced observations or a phase of unknown duration has only
        a lower bound (#890). It is real spend for cost per PASS, which then says it
        is partial, but it must not stand in for a whole run's cost or duration."""
        opus = "claude-opus-5-5"
        complete = _run("1", "wf-a", [opus], Verdict.PASS, "4.00", "2026-10-01T00:00:00+00:00")
        partial = replace(
            _run("2", "wf-a", [opus], Verdict.PASS, "1.00", "2026-10-02T00:00:00+00:00"),
            unpriced_observation_count=2,
            unknown_duration_phase_count=1,
        )
        runs = [replace(complete, duration_seconds=300.0), replace(partial, duration_seconds=20.0)]

        stats = summarize(runs).stats
        [variant] = summarize(runs).variants

        assert (stats.median_cost_usd, stats.incomplete_cost_count) == (Decimal("4.00"), 1)
        assert (stats.median_duration_seconds, stats.incomplete_duration_count) == (300.0, 1)
        assert stats.cost_per_pass_usd == Decimal("2.50")
        assert variant.avg_cost_usd == Decimal("4.00")


class TestBatchReadsForAPageOfRuns:
    """``scores_of`` and ``records``: what a page of executions reads, once each."""

    async def test_scores_of_answers_exactly_the_runs_asked_about(self) -> None:
        stream, handler = await _scored_stream()
        await handler.handle(_score("run-a", Verdict.FAIL))
        await handler.handle(_score("run-b", Verdict.PASS))
        evals = await _replayed(stream, times=1)

        # (_EVAL, run-b) is scored and lies inside the product of the ids
        # asked about, but was not itself asked about.
        scores = await evals.scores_of({(str(_EVAL), "run-a"), (str(_OTHER), "run-b")})

        assert {key: score.verdict for key, score in scores.items()} == {
            (str(_EVAL), "run-a"): Verdict.FAIL
        }
        assert await evals.scores_of(set()) == {}

    async def test_records_names_each_projected_eval_and_omits_the_rest(self) -> None:
        stream, _handler = await _scored_stream()
        evals = await _replayed(stream, times=1)

        records = await evals.records({str(_EVAL), str(_OTHER), "eval-not-projected"})

        assert {eval_id: record.name for eval_id, record in records.items()} == {
            str(_EVAL): "Refactor quality",
            str(_OTHER): "Other",
        }

    async def test_records_leaves_out_a_projected_eval_nobody_asked_about(self) -> None:
        stream, _handler = await _scored_stream()
        evals = await _replayed(stream, times=1)

        # _OTHER is projected too; asking for _EVAL alone must not return it.
        records = await evals.records({str(_EVAL), "eval-not-projected"})

        assert {eval_id: record.name for eval_id, record in records.items()} == {
            str(_EVAL): "Refactor quality"
        }
