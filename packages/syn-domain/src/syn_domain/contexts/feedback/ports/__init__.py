"""Feedback ports (ADR-076). Adapters land with Intake (PR 3) and the Screener (PR 6, 7)."""

from syn_domain.contexts.feedback.ports.ForgeReads import (
    ForgeReads,
    PublishedRelease,
    PullRequestSnapshot,
)
from syn_domain.contexts.feedback.ports.IntakeLog import Disposition, IntakeLog, LeasedSubmission
from syn_domain.contexts.feedback.ports.NonceLedger import NonceLedger
from syn_domain.contexts.feedback.ports.RateBuckets import RateBuckets
from syn_domain.contexts.feedback.ports.ScreeningPort import ScreeningPort

__all__ = [
    "Disposition",
    "ForgeReads",
    "IntakeLog",
    "LeasedSubmission",
    "NonceLedger",
    "PublishedRelease",
    "PullRequestSnapshot",
    "RateBuckets",
    "ScreeningPort",
]
