"""Usage extraction from a stored transcript (#895).

Every assertion here encodes a trap that produces a WRONG BUT PLAUSIBLE number
if you get it backwards, which is the failure mode that matters: a cost that
looks reasonable and is not.

The two harnesses are INVERTED, which is the trap underneath the traps:

    claude  per-message DELTAS   -> SUM them
    codex   running TOTALS       -> take the LAST

Applying either rule to the other harness yields a number nobody would query.
I made that error myself on real data before writing this: I read the FIRST
running total from a codex rollout and reported 12,206 for a session whose
true total is 49,654.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from syn_domain.contexts.agent_sessions.transcript_usage import (
    RolloutDocument,
    SourceFormat,
    extract_usage,
)

_FIXTURES = Path(__file__).parents[2] / "fixtures" / "delegation"


def _codex_document() -> RolloutDocument:
    return json.loads((_FIXTURES / "codex_rollout_usage.json").read_text())


def _claude_document() -> str:
    return (_FIXTURES / "claude_transcript_usage.jsonl").read_text()


@pytest.mark.unit
class TestCodexRollout:
    """Recorded from a real delegated run, not synthesised."""

    def test_takes_the_last_running_total_not_the_first(self) -> None:
        usage = extract_usage(SourceFormat.CODEX_ROLLOUT, _codex_document())

        assert usage.total_tokens == 49654

    def test_summing_running_totals_would_overcount(self) -> None:
        """Guards the guard. If this stopped being true the fixture would no
        longer exercise the trap and the test above would pass vacuously.
        """
        naive = sum(
            r["payload"]["info"]["total_token_usage"]["total_tokens"]  # type: ignore[index]
            for r in _codex_document()
            if r.get("type") == "event_msg"
        )

        assert naive > 49654

    def test_cached_input_is_not_added_to_input(self) -> None:
        """cached_input_tokens is a SUBSET of input_tokens. Adding them
        double-counts, and the sum still looks like a believable token count.
        """
        usage = extract_usage(SourceFormat.CODEX_ROLLOUT, _codex_document())

        assert usage.input_tokens + usage.output_tokens == usage.total_tokens
        assert usage.cache_read_tokens <= usage.input_tokens

    def test_billable_input_excludes_the_cached_portion(self) -> None:
        usage = extract_usage(SourceFormat.CODEX_ROLLOUT, _codex_document())

        assert usage.billable_input_tokens == usage.input_tokens - usage.cache_read_tokens

    def test_model_comes_from_turn_context(self) -> None:
        usage = extract_usage(SourceFormat.CODEX_ROLLOUT, _codex_document())

        assert usage.model


@pytest.mark.unit
class TestClaudeTranscript:
    def test_sums_per_message_deltas(self) -> None:
        """Claude reports per-message deltas, so the total is their SUM.
        Taking the last would report only the final turn.
        """
        usage = extract_usage(SourceFormat.CLAUDE_CODE_JSONL, _claude_document())

        assert usage.input_tokens == 170
        assert usage.output_tokens == 60

    def test_taking_the_last_message_would_undercount(self) -> None:
        """Guards the guard: proves the fixture actually distinguishes the two
        rules rather than having one message.
        """
        usage = extract_usage(SourceFormat.CLAUDE_CODE_JSONL, _claude_document())

        assert usage.output_tokens > 25

    def test_cache_fields_are_kept_separate(self) -> None:
        usage = extract_usage(SourceFormat.CLAUDE_CODE_JSONL, _claude_document())

        assert usage.cache_creation_tokens == 500
        assert usage.cache_read_tokens == 1200

    def test_non_assistant_lines_are_ignored(self) -> None:
        usage = extract_usage(SourceFormat.CLAUDE_CODE_JSONL, _claude_document())

        assert usage.message_count == 3


@pytest.mark.unit
class TestRefusesRatherThanGuesses:
    def test_an_unknown_source_format_is_refused(self) -> None:
        """A silently-zero result is worse than an error: it reads as a free
        delegation rather than an unparsed one.
        """
        with pytest.raises(ValueError, match="unsupported"):
            extract_usage("some-future-harness", {})  # type: ignore[arg-type]

    def test_a_transcript_with_no_usage_is_not_reported_as_zero_cost(self) -> None:
        usage = extract_usage(SourceFormat.CODEX_ROLLOUT, [{"type": "session_meta"}])

        assert usage.has_usage is False

    def test_a_real_transcript_reports_that_it_has_usage(self) -> None:
        usage = extract_usage(SourceFormat.CODEX_ROLLOUT, _codex_document())

        assert usage.has_usage is True


@pytest.mark.unit
class TestDetectsAFormatThatMovedUnderUs:
    """A stored format can change while its source_format label does not.

    The omni image is bumping codex 0.144.6 -> 0.150.1. If that release
    restructures the rollout while the store still labels it 'rollout', a
    parser does not fail: it returns a smaller, plausible number. That is
    indistinguishable from a cheap delegation, which is precisely the failure
    being fixed rather than a new one.
    """

    def test_a_real_transcript_reconciles(self) -> None:
        usage = extract_usage(SourceFormat.CODEX_ROLLOUT, _codex_document())

        assert usage.is_self_consistent is True

    def test_parts_that_do_not_reconcile_are_flagged(self) -> None:
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

        usage = extract_usage(SourceFormat.CODEX_ROLLOUT, moved)

        assert usage.has_usage is True
        assert usage.is_self_consistent is False

    def test_cached_larger_than_input_is_flagged(self) -> None:
        """cached is a SUBSET of input. If it ever exceeds it, the subset
        relationship this pricing depends on has changed."""
        inverted = [
            {
                "type": "event_msg",
                "payload": {
                    "info": {
                        "total_token_usage": {
                            "input_tokens": 10,
                            "output_tokens": 5,
                            "cached_input_tokens": 900,
                            "total_tokens": 15,
                        }
                    }
                },
            }
        ]

        assert extract_usage(SourceFormat.CODEX_ROLLOUT, inverted).is_self_consistent is False
