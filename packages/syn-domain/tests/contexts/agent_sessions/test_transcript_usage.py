"""Usage extraction from a stored transcript (#895).

Every assertion encodes a trap that yields a WRONG BUT PLAUSIBLE number if
inverted, which is the failure that matters: a cost that looks reasonable and
is not.

BOTH FIXTURES ARE REAL, recorded from delegated runs on the omni image pinned
at sha256:83834d63 (delegation plugin 1.2.3), with prompt and response content
stripped. Provenance matters here: the first version of this file used a
hand-authored Claude fixture with round numbers, and that is exactly where the
worst bug hid. A synthesised transcript encodes the author's assumption and
then confirms it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.agent_sessions.transcript_usage import (
    NoUsage,
    PricedUsage,
    RolloutDocument,
    RolloutRecord,
    SourceFormat,
    UnpricedUsage,
    extract_usage,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, MutableMapping

_FIXTURES = Path(__file__).parents[2] / "fixtures" / "delegation"


def _codex_document() -> RolloutDocument:
    return json.loads((_FIXTURES / "codex_rollout_usage.json").read_text())


def _claude_document() -> str:
    return (_FIXTURES / "claude_transcript_usage.jsonl").read_text()


def _priced(result: object) -> PricedUsage:
    assert isinstance(result, PricedUsage), f"expected priceable usage, got {result!r}"
    return result


@pytest.mark.unit
class TestTheHarnessesDoNotShareSemantics:
    """The bug this class exists for priced a real Claude delegate at ZERO
    input tokens, by applying codex's cache semantics to Claude.
    """

    def test_claude_input_is_not_reduced_by_cache_reads(self) -> None:
        """Real measured delegate: input 7, cache_read 28,340.

        Under codex semantics cached is a SUBSET of input, so cached can never
        exceed it. Here it is four thousand times larger, which is the proof
        that Claude's buckets are independent. Subtracting would report 0.
        """
        usage = _priced(extract_usage(SourceFormat.CLAUDE_CODE_JSONL, _claude_document()))

        assert usage.cache_read_tokens > usage.uncached_input_tokens
        assert usage.uncached_input_tokens == 7

    def test_codex_input_is_reduced_by_its_cached_subset(self) -> None:
        """Codex's input INCLUDES the cached portion, so billable is the
        remainder. Not subtracting double-counts.
        """
        usage = _priced(extract_usage(SourceFormat.CODEX_ROLLOUT, _codex_document()))

        assert usage.uncached_input_tokens == 49250 - 45056
        assert usage.cache_read_tokens == 45056

    def test_canonical_buckets_are_disjoint_for_both(self) -> None:
        """The point of normalising: after parsing, a total is just a sum, and
        the caller never needs to know which harness produced it.
        """
        codex = _priced(extract_usage(SourceFormat.CODEX_ROLLOUT, _codex_document()))
        claude = _priced(extract_usage(SourceFormat.CLAUDE_CODE_JSONL, _claude_document()))

        assert codex.total_tokens == 4194 + 45056 + 0 + 404
        assert claude.total_tokens == 7 + 28340 + 56843 + 214


@pytest.mark.unit
class TestCodexRollout:
    def test_takes_the_last_running_total_not_the_first(self) -> None:
        usage = _priced(extract_usage(SourceFormat.CODEX_ROLLOUT, _codex_document()))

        assert usage.uncached_input_tokens + usage.cache_read_tokens + usage.output_tokens == 49654

    def test_summing_running_totals_would_overcount(self) -> None:
        """Guards the guard: if this stopped being true, the fixture would no
        longer exercise the trap and the test above would pass vacuously.
        """
        naive = sum(
            r["payload"]["info"]["total_token_usage"]["total_tokens"]  # type: ignore[index]
            for r in _codex_document()
            if r.get("type") == "event_msg"
        )

        assert naive > 49654

    def test_model_comes_from_turn_context(self) -> None:
        assert _priced(extract_usage(SourceFormat.CODEX_ROLLOUT, _codex_document())).model


@pytest.mark.unit
class TestClaudeTranscript:
    def test_sums_per_message_deltas(self) -> None:
        usage = _priced(extract_usage(SourceFormat.CLAUDE_CODE_JSONL, _claude_document()))

        assert usage.output_tokens == 214
        assert usage.message_count == 3

    def test_cache_buckets_are_kept_separate(self) -> None:
        usage = _priced(extract_usage(SourceFormat.CLAUDE_CODE_JSONL, _claude_document()))

        assert usage.cache_creation_tokens == 56843
        assert usage.cache_read_tokens == 28340


@pytest.mark.unit
class TestAnUntrustworthyParseExposesNoNumbers:
    """An advisory flag beside plausible counters is not enough, because a
    caller reads the counters. UnpricedUsage carries none, so a bad parse is a
    visible gap rather than a confident undercount.
    """

    def test_empty_usage_object_is_unpriced_not_free(self) -> None:
        result = extract_usage(
            SourceFormat.CODEX_ROLLOUT,
            [{"type": "event_msg", "payload": {"info": {"total_token_usage": {}}}}],
        )

        assert isinstance(result, UnpricedUsage)

    def test_a_moved_total_is_unpriced(self) -> None:
        moved = [
            {
                "type": "event_msg",
                "payload": {
                    "info": {
                        "total_token_usage": {
                            "input_tokens": 100,
                            "output_tokens": 10,
                            "cached_input_tokens": 50,
                            "total_tokens": 9999,
                        }
                    }
                },
            }
        ]

        assert isinstance(extract_usage(SourceFormat.CODEX_ROLLOUT, moved), UnpricedUsage)

    def test_decreasing_cumulative_totals_are_unpriced(self) -> None:
        """Only cumulative readings justify last-wins. If they decrease they
        are not cumulative, and last-wins is then the wrong rule entirely.
        """

        def event(i: int, o: int, c: int, t: int) -> RolloutRecord:
            return {
                "type": "event_msg",
                "payload": {
                    "info": {
                        "total_token_usage": {
                            "input_tokens": i,
                            "output_tokens": o,
                            "cached_input_tokens": c,
                            "total_tokens": t,
                        }
                    }
                },
            }

        shrinking = [event(500, 50, 100, 550), event(100, 10, 20, 110)]

        assert isinstance(extract_usage(SourceFormat.CODEX_ROLLOUT, shrinking), UnpricedUsage)

    def test_a_negative_count_is_unpriced(self) -> None:
        negative = [
            {
                "type": "event_msg",
                "payload": {
                    "info": {
                        "total_token_usage": {
                            "input_tokens": -5,
                            "output_tokens": 10,
                            "cached_input_tokens": 0,
                            "total_tokens": 5,
                        }
                    }
                },
            }
        ]

        assert isinstance(extract_usage(SourceFormat.CODEX_ROLLOUT, negative), UnpricedUsage)

    def test_a_malformed_claude_line_makes_the_total_unknowable(self) -> None:
        """A line we cannot read may have carried usage, so the rest is not a
        total, it is a fragment.
        """
        broken = '{"message":{"model":"m","usage":{"input_tokens":5,"output_tokens":1,'
        broken += '"cache_creation_input_tokens":0,"cache_read_input_tokens":0}}}\n{unreadable'

        assert isinstance(extract_usage(SourceFormat.CLAUDE_CODE_JSONL, broken), UnpricedUsage)

    def test_a_mixed_model_transcript_is_unpriced(self) -> None:
        """Tokens aggregate; a model does not. Billing the whole session at
        whichever model happened to be last is a silent mispricing, and
        delegates can switch model mid-session.
        """
        u = '"usage":{"input_tokens":5,"output_tokens":1,'
        u += '"cache_creation_input_tokens":0,"cache_read_input_tokens":0}'
        mixed = '{"message":{"model":"model-a",' + u + "}}\n"
        mixed += '{"message":{"model":"model-b",' + u + "}}"

        result = extract_usage(SourceFormat.CLAUDE_CODE_JSONL, mixed)

        assert isinstance(result, UnpricedUsage)
        assert "multiple models" in result.reason

    def test_no_usage_is_distinct_from_unpriced(self) -> None:
        """A transcript that carried nothing and one we could not read are
        different facts, and only one of them is a bug.
        """
        assert isinstance(
            extract_usage(SourceFormat.CODEX_ROLLOUT, [{"type": "session_meta"}]), NoUsage
        )

    def test_an_unknown_source_format_degrades_rather_than_raising(self) -> None:
        """One unrecognised session must not fail the import of every session
        beside it. A new harness, or a literal drifting the way
        codex-rollout-jsonl did, should be a gap and not an outage.
        """
        result = extract_usage("some-future-harness", "")

        assert isinstance(result, UnpricedUsage)
        assert "some-future-harness" in result.reason


@pytest.mark.unit
class TestFormatLiteralsMatchTheStore:
    """The literals belong to the store, so they are pinned to real records.

    Naming the codex format after its informal name gave "rollout", which
    matched nothing: every real codex transcript reports
    "codex-rollout-jsonl". Unit tests did not catch it because they passed the
    literal the code expected, so they agreed with the implementation rather
    than with the store.

    This fixture is metadata captured from live store records, so drift in
    EITHER direction fails: ours changing, or the store's.
    """

    def _recorded(self) -> list[dict[str, str]]:
        return json.loads((_FIXTURES / "store_source_formats.json").read_text())

    def test_every_recorded_format_is_one_we_dispatch_on(self) -> None:
        known = {fmt.value for fmt in SourceFormat}
        recorded = {row["source_format"] for row in self._recorded()}

        assert recorded <= known, f"store emits formats we cannot read: {recorded - known}"

    def test_the_codex_literal_is_the_store_value_not_the_informal_name(self) -> None:
        codex = next(r for r in self._recorded() if r["agent"] == "Codex")

        assert SourceFormat.CODEX_ROLLOUT.value == codex["source_format"]
        assert SourceFormat.CODEX_ROLLOUT.value != "rollout"

    def test_the_claude_literal_matches_too(self) -> None:
        claude = next(r for r in self._recorded() if r["agent"] == "ClaudeCode")

        assert SourceFormat.CLAUDE_CODE_JSONL.value == claude["source_format"]

    def test_a_real_codex_format_string_actually_dispatches(self) -> None:
        """End to end on the value the store hands us, not the one we assume.

        Before the fix this raised ValueError for every real codex transcript.
        """
        codex = next(r for r in self._recorded() if r["agent"] == "Codex")

        result = extract_usage(codex["source_format"], _codex_document())

        assert isinstance(result, PricedUsage)


@pytest.mark.unit
class TestTheRetrievalPathTheCallerWillActuallyUse:
    """Exercises how the store hands data over, not how we wish it did.

    Nothing tested the retrieval path before, and that gap hid two defects in
    consecutive rounds: a format literal that matched no real record, and a
    document type the store does not produce. Both times the code was
    self-consistent and disagreed with the store.

    GET /v1/sessions/<id>/raw serves application/json, so a caller reading
    response.json() gets a list and one reading response.text gets a string.
    Both must work, or whichever caller guesses wrong silently loses a
    harness.
    """

    def _store_format(self, agent: str) -> str:
        recorded = json.loads((_FIXTURES / "store_source_formats.json").read_text())
        return next(r["source_format"] for r in recorded if r["agent"] == agent)

    def test_codex_priced_from_parsed_json(self) -> None:
        result = extract_usage(self._store_format("Codex"), _codex_document())

        assert isinstance(result, PricedUsage)

    def test_codex_priced_from_raw_text(self) -> None:
        """The failure that would have silently halved delegate cost: a caller
        reading response.text got UnpricedUsage for every codex session.
        """
        as_text = json.dumps(_codex_document())

        result = extract_usage(self._store_format("Codex"), as_text)

        assert isinstance(result, PricedUsage)

    def test_both_routes_agree(self) -> None:
        """Same transcript, two ways of reading it, one answer. Otherwise the
        cost depends on how the caller happened to deserialise.
        """
        parsed = extract_usage(self._store_format("Codex"), _codex_document())
        as_text = extract_usage(self._store_format("Codex"), json.dumps(_codex_document()))

        assert parsed == as_text

    def test_claude_priced_from_raw_text(self) -> None:
        result = extract_usage(self._store_format("ClaudeCode"), _claude_document())

        assert isinstance(result, PricedUsage)

    def test_a_wrong_document_type_names_the_type_not_the_format(self) -> None:
        """The message must point at the real problem.

        It previously called the format unsupported AND listed it as known, in
        one sentence, which sent a reader after source_format when the format
        was fine. The code's explanation of an error is not the error.
        """
        result = extract_usage(self._store_format("ClaudeCode"), [{"type": "session_meta"}])

        assert isinstance(result, UnpricedUsage)
        assert "expects JSONL text" in result.reason
        assert "unsupported" not in result.reason

    def test_unparseable_codex_text_is_unpriced_not_free(self) -> None:
        result = extract_usage(self._store_format("Codex"), "{not json")

        assert isinstance(result, UnpricedUsage)


def _codex_event(
    *,
    inp: int,
    out: int,
    cached: int,
    total: int,
    delta: int | None = None,
    extra: Mapping[str, object] | None = None,
) -> RolloutRecord:
    usage: MutableMapping[str, object] = {
        "input_tokens": inp,
        "output_tokens": out,
        "cached_input_tokens": cached,
        "total_tokens": total,
    }
    if extra:
        usage.update(extra)
    info: MutableMapping[str, object] = {"total_token_usage": usage}
    if delta is not None:
        info["last_token_usage"] = {"total_tokens": delta}
    return {"type": "event_msg", "payload": {"info": info}}


@pytest.mark.unit
class TestTheAdversarialCasesThatPreviouslyPriced:
    """Three cases that returned PricedUsage with numbers that were wrong.

    Each is a way for the arithmetic to look tidy while the answer is stale,
    truncated or underpriced. All three underreport, which is the direction
    every failure in this issue has gone.
    """

    def test_a_restructured_final_record_is_refused_not_skipped(self) -> None:
        """The stale-total failure with a new trigger.

        A final record whose usage key moved was IGNORED, so the preceding
        cumulative total was returned as though it were current: a long
        session priced at an early turn's cost, which is the 12,206-against-
        49,654 error wearing different clothes.
        """
        document = [
            _codex_event(inp=100, out=10, cached=0, total=110),
            # same record shape, usage relocated under a renamed key
            {"type": "event_msg", "payload": {"info": {"token_usage": {"total_tokens": 999}}}},
        ]

        result = extract_usage(SourceFormat.CODEX_ROLLOUT, document)

        assert isinstance(result, UnpricedUsage)

    def test_a_cached_only_decrease_is_refused(self) -> None:
        """Monotonicity previously covered input, output and total only.

        cached is precisely the component the codex subtraction depends on, so
        it was the one component whose corruption changed the billable figure
        while every checked number still rose.
        """
        document = [
            _codex_event(inp=100, out=10, cached=90, total=110),
            _codex_event(inp=200, out=20, cached=5, total=220),
        ]

        result = extract_usage(SourceFormat.CODEX_ROLLOUT, document)

        assert isinstance(result, UnpricedUsage)
        assert "decreased" in result.reason

    def test_a_malformed_cache_write_is_refused_not_zeroed(self) -> None:
        """`_as_count(...) or 0` turned a malformed value into zero.

        cache_write is the field the CLI bump just added on the codex side, so
        it is both new and the most likely to arrive in an unexpected shape.
        Zeroing it underprices silently.
        """
        document = [
            _codex_event(
                inp=100,
                out=10,
                cached=0,
                total=110,
                extra={"cache_write_input_tokens": "not-a-number"},
            )
        ]

        result = extract_usage(SourceFormat.CODEX_ROLLOUT, document)

        assert isinstance(result, UnpricedUsage)

    def test_an_absent_cache_write_is_still_fine(self) -> None:
        """Guards the guard: absent and malformed must not be conflated, or
        every rollout today would refuse to price.
        """
        result = extract_usage(SourceFormat.CODEX_ROLLOUT, _codex_document())

        assert isinstance(result, PricedUsage)

    def test_deltas_that_disagree_with_the_final_total_are_refused(self) -> None:
        """The one invariant not derivable from the cumulative series itself.

        A cumulative sequence can be internally tidy and still wrong; only the
        per-turn deltas can contradict it independently.
        """
        document = [
            _codex_event(inp=100, out=10, cached=0, total=110, delta=110),
            _codex_event(inp=200, out=20, cached=0, total=220, delta=999),
        ]

        result = extract_usage(SourceFormat.CODEX_ROLLOUT, document)

        assert isinstance(result, UnpricedUsage)
        assert "deltas sum" in result.reason

    def test_deltas_that_agree_still_price(self) -> None:
        document = [
            _codex_event(inp=100, out=10, cached=0, total=110, delta=110),
            _codex_event(inp=200, out=20, cached=0, total=220, delta=110),
        ]

        assert isinstance(extract_usage(SourceFormat.CODEX_ROLLOUT, document), PricedUsage)

    def test_mixed_model_codex_is_refused_like_claude(self) -> None:
        """The harnesses disagreed on the same hazard: claude refused, codex
        billed everything at whichever model came last.
        """
        document = [
            {"type": "turn_context", "payload": {"model": "model-a"}},
            _codex_event(inp=100, out=10, cached=0, total=110),
            {"type": "turn_context", "payload": {"model": "model-b"}},
            _codex_event(inp=200, out=20, cached=0, total=220),
        ]

        result = extract_usage(SourceFormat.CODEX_ROLLOUT, document)

        assert isinstance(result, UnpricedUsage)
        assert "multiple models" in result.reason
