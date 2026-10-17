"""ScreenedText, ScreeningPolicy, NearDuplicateMatcher and ResolutionPolicy (ADR-076-feedback-ticketing)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from syn_domain.contexts.feedback import (
    MAX_SCREENED_CHARS,
    FixObservation,
    MatchBucket,
    MatchCandidate,
    NearDuplicateMatcher,
    Priority,
    ResolutionPolicy,
    ResolutionRule,
    ScreenedText,
    ScreeningDecision,
    ScreeningPolicy,
    ScreeningResult,
    ScreeningThresholds,
    ScreeningVerdict,
    TicketType,
)

pytestmark = pytest.mark.unit

T0 = datetime(2026, 10, 17, tzinfo=UTC)


class TestScreenedText:
    def test_strips_invisible_and_bidi_code_points(self) -> None:
        raw = "save​ but‮ton\x00 broken⁦"
        assert ScreenedText.screen(raw).text == "save button broken"

    def test_nfc_and_collapsed_whitespace(self) -> None:
        assert ScreenedText.screen("  café \n\t is   shut ").text == "café is shut"

    def test_caps_at_the_limit(self) -> None:
        assert len(ScreenedText.screen("a " * 5000).text) == MAX_SCREENED_CHARS

    @pytest.mark.parametrize(
        "secret",
        [
            "sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAA",
            "ghp_" + "a" * 36,
            "github_pat_" + "b" * 40,
            "AKIAABCDEFGHIJKLMNOP",
            "Bearer eyJhbGciOiJIUzI1NiJ9.abcdefgh",
            "-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----",
        ],
    )
    def test_redacts_secret_shapes(self, secret: str) -> None:
        screened = ScreenedText.screen(f"my key is {secret} help")
        assert "[redacted]" in screened.text
        assert secret.split()[-1][-8:] not in screened.text

    def test_redaction_runs_before_the_cap(self) -> None:
        secret = "ghp_" + "c" * 36
        screened = ScreenedText.screen("x" * (MAX_SCREENED_CHARS - 10) + " " + secret)
        assert "ghp_" not in screened.text

    def test_same_words_hash_the_same(self) -> None:
        assert (
            ScreenedText.screen("Save  is broken").content_hash
            == ScreenedText.screen("Save is​ broken").content_hash
        )


def _result(verdict: ScreeningVerdict, confidence: float) -> ScreeningResult:
    return ScreeningResult(
        verdict=verdict, type=TicketType.BUG, priority=Priority.P2, confidence=confidence
    )


class TestScreeningPolicy:
    @pytest.mark.parametrize(
        ("verdict", "confidence", "decision"),
        [
            (ScreeningVerdict.CLEAN, 0.95, ScreeningDecision.OPEN),
            (ScreeningVerdict.CLEAN, 0.3, ScreeningDecision.QUARANTINE),
            (ScreeningVerdict.SPAM, 0.95, ScreeningDecision.DROP),
            (ScreeningVerdict.SPAM, 0.5, ScreeningDecision.QUARANTINE),
            (ScreeningVerdict.QUARANTINE, 1.0, ScreeningDecision.QUARANTINE),
        ],
    )
    def test_doubt_lands_in_quarantine(
        self, verdict: ScreeningVerdict, confidence: float, decision: ScreeningDecision
    ) -> None:
        assert (
            ScreeningPolicy.decide(_result(verdict, confidence), ScreeningThresholds()) is decision
        )


class TestNearDuplicateMatcher:
    BUCKET = MatchBucket.of(route="/executions", ticket_type=TicketType.BUG)

    def _candidate(
        self, ticket_id: str, text: str, bucket: MatchBucket | None = None
    ) -> MatchCandidate:
        return MatchCandidate(
            ticket_id=ticket_id, bucket=bucket or self.BUCKET, text=ScreenedText.screen(text)
        )

    def test_matches_the_most_similar_candidate_in_the_bucket(self) -> None:
        text = ScreenedText.screen("the cancel button on the execution page does nothing at all")
        match = NearDuplicateMatcher(threshold=0.3).best_match(
            text,
            self.BUCKET,
            [
                self._candidate("t-far", "dark mode colours are wrong on the settings page"),
                self._candidate("t-near", "the cancel button on the execution page does nothing"),
            ],
        )
        assert match is not None
        assert match.ticket_id == "t-near"
        assert 0.3 <= match.similarity < 1.0

    def test_never_matches_across_buckets(self) -> None:
        text = ScreenedText.screen("the cancel button does nothing")
        other = MatchBucket.of(route="/settings", ticket_type=TicketType.BUG)
        candidates = [self._candidate("t-1", "the cancel button does nothing", other)]
        assert NearDuplicateMatcher().best_match(text, self.BUCKET, candidates) is None

    def test_without_a_route_the_type_is_the_bucket(self) -> None:
        assert MatchBucket.of(route=None, ticket_type=TicketType.BUG) != MatchBucket.of(
            route=None, ticket_type=TicketType.FEATURE
        )

    def test_below_threshold_is_no_match(self) -> None:
        text = ScreenedText.screen("export to csv please")
        candidates = [self._candidate("t-1", "the cancel button does nothing")]
        assert NearDuplicateMatcher().best_match(text, self.BUCKET, candidates) is None


def _seen(contains_fix: bool = True) -> FixObservation:
    return FixObservation(contains_fix=contains_fix, version="0.30.0-beta.1", observed_at=T0)


class TestResolutionPolicy:
    def test_a_release_resolves(self) -> None:
        rule = ResolutionPolicy.decide(released=True, signed_reporters=set(), observations={})
        assert rule is ResolutionRule.RELEASED

    def test_every_signed_reporter_must_have_observed_the_fix(self) -> None:
        reporters = {"src-a", "src-b"}
        assert (
            ResolutionPolicy.decide(
                released=False, signed_reporters=reporters, observations={"src-a": _seen()}
            )
            is None
        )
        assert (
            ResolutionPolicy.decide(
                released=False,
                signed_reporters=reporters,
                observations={"src-a": _seen(), "src-b": _seen()},
            )
            is ResolutionRule.ALL_REPORTERS_OBSERVED
        )

    def test_an_observation_without_the_fix_does_not_count(self) -> None:
        rule = ResolutionPolicy.decide(
            released=False, signed_reporters={"src-a"}, observations={"src-a": _seen(False)}
        )
        assert rule is None

    def test_no_signed_reporter_is_not_everyone(self) -> None:
        rule = ResolutionPolicy.decide(
            released=False, signed_reporters=set(), observations={"src-x": _seen()}
        )
        assert rule is None
