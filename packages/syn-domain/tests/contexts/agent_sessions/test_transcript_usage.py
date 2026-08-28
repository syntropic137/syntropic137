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

    def test_an_unknown_source_format_is_refused(self) -> None:
        with pytest.raises(ValueError, match="unsupported"):
            extract_usage("some-future-harness", "")  # type: ignore[arg-type]
