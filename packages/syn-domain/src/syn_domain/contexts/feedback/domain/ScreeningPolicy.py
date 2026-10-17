"""Screening Policy: what a Screening Verdict means for one submission (ADR-076-feedback-ticketing).

Pure. The classifier says what it thinks; this decides what the context does
about it, so a change of classifier never changes the rule.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from syn_domain.contexts.feedback._shared.value_objects import Priority, TicketType


class ScreeningVerdict(StrEnum):
    CLEAN = "clean"
    QUARANTINE = "quarantine"
    SPAM = "spam"


class ScreeningResult(BaseModel):
    """One classifier pass over a Screened Text."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    verdict: ScreeningVerdict
    type: TicketType
    priority: Priority
    confidence: float = Field(ge=0.0, le=1.0)


class ScreeningThresholds(BaseModel):
    """Confidence a verdict needs before the policy acts on it unseen."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    open_at: float = Field(default=0.6, ge=0.0, le=1.0)
    drop_at: float = Field(default=0.9, ge=0.0, le=1.0)


class ScreeningDecision(StrEnum):
    OPEN = "open"
    QUARANTINE = "quarantine"
    DROP = "drop"


class ScreeningPolicy:
    """Doubt always lands in quarantine, never in the open or in the bin.

    Clean text opens only when the classifier is confident; spam is dropped only
    when it is confident. Everything else waits for the owner.
    """

    @staticmethod
    def decide(result: ScreeningResult, thresholds: ScreeningThresholds) -> ScreeningDecision:
        if result.verdict is ScreeningVerdict.CLEAN and result.confidence >= thresholds.open_at:
            return ScreeningDecision.OPEN
        if result.verdict is ScreeningVerdict.SPAM and result.confidence >= thresholds.drop_at:
            return ScreeningDecision.DROP
        return ScreeningDecision.QUARANTINE
