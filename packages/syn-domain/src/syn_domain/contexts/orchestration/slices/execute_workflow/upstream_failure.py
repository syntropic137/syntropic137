"""What kind of upstream fault ended an agent attempt, and what it asks of us (#1592).

Two failures that both read as "the platform failed" demand OPPOSITE
responses. A provider with no capacity this second has told us nothing about
the request, and the same attempt a few seconds later is likely to succeed:
it is transient, and the phase is resumable. A provider that refused our
credentials will refuse them on every attempt until somebody fixes the login:
retrying only spends the phase's budget again, and the run needs an operator.

So the domain asks ONE question - "what kind of upstream fault was this?" -
through `UpstreamFailureReader`, and decides what each kind means here.
Recognising a kind from a harness's own words is harness knowledge, which
changes whenever a CLI does, and is not decided here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar, Protocol

__all__ = [
    "UPSTREAM_FAILURES",
    "QuotaExhaustion",
    "StreamReasonUpstreamFailureReader",
    "UpstreamFailureError",
    "UpstreamFailureKind",
    "UpstreamFailureReader",
]

from syn_domain.contexts.orchestration.slices.execute_workflow.codex_faults import (
    codex_fault_reason,
    codex_login_fault_reason,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    ApiErrorType,
    api_error_label,
    api_error_with_message,
)
from syn_shared.upstream_failure import QuotaExhaustion, UpstreamFailureError, UpstreamFailureKind

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


class UpstreamFailureReader(Protocol):
    """The port: what kind of upstream fault an attempt's normalised failure reason is."""

    def kind_of(self, reason: str | None) -> UpstreamFailureKind | None:
        """The kind, or None when the attempt reported no fault at all."""
        ...

    def quota_of(self, reason: str | None) -> QuotaExhaustion | None:
        """Whose quota is spent and until when, or None when ``reason`` is not a quota fault.

        `kind_of` is `QUOTA` exactly when this is not None.
        """
        ...


#: The one sentence codex says about its own capacity, observed in #1303. Codex
#: does not promise to keep saying it; a new phrasing reads as `UNKNOWN`,
#: which is not retried - the safe direction to be wrong in.
_CODEX_AT_CAPACITY = "Selected model is at capacity. Please try a different model."


#: What codex says when the account's allowance is spent, as fragments of the
#: one real line observed 2026-10-06 (PC-83): "You've hit your usage limit.
#: Visit https://chatgpt.com/codex/settings/usage to purchase more credits or
#: try again at Oct 9th, 2026 9:10 PM." Fragments, not the whole line, so the
#: reset date and URL may change without the match breaking; matched
#: case-insensitively and only inside codex's own fault line.
_CODEX_QUOTA_PHRASES: tuple[str, ...] = ("hit your usage limit", "purchase more credits")

#: What claude says when the account's allowance is spent. EMPTY, deliberately:
#: no real claude quota message exists in this repo, agentic-workspace or any
#: fixture, and a spelling invented here would match nothing claude writes.
#: Until it is filled a claude quota failure reads as UNKNOWN - not retried,
#: and no fallback run.
# TODO(#1669): capture the real claude usage-limit line (its sentence, any
# `|<epoch>` reset suffix, any "resets ..." phrase and its zone, and which
# stream channel carries it) and add it here with a reset reader.
_CLAUDE_QUOTA_PHRASES: tuple[str, ...] = ()

#: What codex says when its content filter declines the request, as a fragment
#: of the one real line in this repo (exec-61dad6055e6f, kept as
#: `tests/fixtures/codex/codex_turn_failed.jsonl`; exec-898cd870650e said the
#: same): "This content was flagged for possible cybersecurity risk. If this
#: seems wrong, try rephrasing your request. ..." A fragment so the trailing
#: advice and URL may change without the match breaking; matched
#: case-insensitively and only inside codex's own fault line.
_CODEX_REFUSAL_PHRASES: tuple[str, ...] = ("flagged for possible cybersecurity risk",)

#: Claude's content refusal has no entry: no real claude refusal output exists
#: in this repo, agentic-workspace or any fixture, and a spelling invented here
#: would match nothing claude writes. A claude refusal reads as UNKNOWN.

#: Codex's reset time, when it names a date. The CLI prints no zone; the
#: workspace container runs in UTC, so the time is read as UTC. A time with no
#: date ("try again at 9:10 PM") cannot be placed and reads as unstated.
_CODEX_QUOTA_RESET = re.compile(
    r"try again at (?P<month>[A-Z][a-z]{2})[a-z]* (?P<day>\d{1,2})(?:st|nd|rd|th)?, "
    r"(?P<year>\d{4}) (?P<hour>\d{1,2}):(?P<minute>\d{2}) ?(?P<ampm>[AP]M)"
)


def _codex_quota_reset(message: str) -> datetime | None:
    match = _CODEX_QUOTA_RESET.search(message)
    if match is None:
        return None
    try:
        stamp = datetime.strptime(
            "{month} {day} {year} {hour}:{minute} {ampm}".format(**match.groupdict()),
            "%b %d %Y %I:%M %p",
        )
    except ValueError:
        return None
    return stamp.replace(tzinfo=UTC)


def _no_reset(_message: str) -> datetime | None:
    return None


@dataclass(frozen=True)
class _QuotaSpelling:
    """How one provider says its quota is spent: where, in which words, and until when.

    ``fault_line`` is the prefix the provider's own stream processor writes on
    a fault. A phrase counts only after it, so agent prose that quotes one
    cannot forge a quota - which would buy a run on the fallback agent.
    """

    provider: str
    fault_line: str
    phrases: tuple[str, ...]
    resets_at: Callable[[str], datetime | None]

    def quota_of(self, reason: str) -> QuotaExhaustion | None:
        if not reason.startswith(self.fault_line):
            return None
        message = reason.removeprefix(self.fault_line)
        folded = message.casefold()
        if not any(phrase.casefold() in folded for phrase in self.phrases):
            return None
        return QuotaExhaustion(provider=self.provider, resets_at=self.resets_at(message))


#: One entry per provider. Adding a provider's quota words is a data change here.
_QUOTA_SPELLINGS: tuple[_QuotaSpelling, ...] = (
    _QuotaSpelling(
        provider="codex",
        fault_line=codex_fault_reason(""),
        phrases=_CODEX_QUOTA_PHRASES,
        resets_at=_codex_quota_reset,
    ),
    # Which fault line claude's quota arrives on is unknown too (#1669); the
    # API-error prefix is where every other claude upstream fault is written.
    _QuotaSpelling(
        provider="claude",
        fault_line=api_error_with_message(ApiErrorType.RATE_LIMIT, ""),
        phrases=_CLAUDE_QUOTA_PHRASES,
        resets_at=_no_reset,
    ),
)


#: Each provider's fault line, with the words that mark a refusal inside it.
#: The fault line is required for the reason `_QuotaSpelling` requires it: a
#: refusal buys a run on the fallback agent, so agent prose quoting the
#: sentence must not forge one.
_REFUSAL_SPELLINGS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (codex_fault_reason(""), _CODEX_REFUSAL_PHRASES),
)


def _is_refusal(reason: str) -> bool:
    for fault_line, phrases in _REFUSAL_SPELLINGS:
        if not reason.startswith(fault_line):
            continue
        folded = reason.removeprefix(fault_line).casefold()
        if any(phrase.casefold() in folded for phrase in phrases):
            return True
    return False


def _claude_spellings(
    kind: UpstreamFailureKind, faults: tuple[tuple[ApiErrorType, str], ...]
) -> Iterator[tuple[str, UpstreamFailureKind]]:
    """Every spelling the claude parser gives these faults, with and without the status."""
    for error_type, status in faults:
        yield api_error_label(error_type), kind
        yield api_error_label(error_type, status), kind


class StreamReasonUpstreamFailureReader:
    """The port, read from the stream processors' normalised `error_reason` text.

    TODO(#1605): harness text does not belong in syn-domain. This adapter
    exists only until agentic-workspace's harness adapters carry the kind on
    their normalised result; then it is replaced by one that reads that field.

    MEMBERSHIP IS BY EQUALITY, NEVER CONTAINMENT. `Rate limit reached; quota
    resets next month` CONTAINS "rate limit" and is permanent, and an agent
    that merely quotes one of these sentences must not forge the signal. Each
    spelling is asked of the function that produces it, so this table cannot
    disagree with the string a stream processor actually wrote.
    """

    _KINDS: ClassVar[dict[str, UpstreamFailureKind]] = {
        **dict(
            _claude_spellings(UpstreamFailureKind.CAPACITY, ((ApiErrorType.OVERLOADED, "529"),))
        ),
        **dict(
            _claude_spellings(UpstreamFailureKind.RATE_LIMITED, ((ApiErrorType.RATE_LIMIT, "429"),))
        ),
        **dict(
            _claude_spellings(
                UpstreamFailureKind.AUTH,
                ((ApiErrorType.AUTHENTICATION, "401"), (ApiErrorType.PERMISSION, "403")),
            )
        ),
        codex_fault_reason(_CODEX_AT_CAPACITY): UpstreamFailureKind.CAPACITY,
    }

    #: Auth faults the parsers report WITH detail appended: a codex login fault
    #: carries the CLI's log line, a claude error body its own message. Each
    #: prefix is what its producer writes with empty detail, and it is matched
    #: only at the start of the reason. Only `AUTH` is matched this way: it is
    #: never retried, so text that forges a prefix can at worst stop a retry
    #: `UNKNOWN` would not have made either - never cause one.
    _AUTH_PREFIXES: ClassVar[tuple[str, ...]] = (
        *(codex_login_fault_reason(status, "") for status in ("401", "403", "")),
        api_error_with_message(ApiErrorType.AUTHENTICATION, ""),
        api_error_with_message(ApiErrorType.PERMISSION, ""),
    )

    def quota_of(self, reason: str | None) -> QuotaExhaustion | None:
        # A quota is never retried, so a forged one can at worst stop a retry
        # UNKNOWN would not have made either - but it can buy a run on the
        # fallback agent, so each provider's words are read only inside that
        # provider's own fault line. See `_QuotaSpelling`.
        if reason is None:
            return None
        for spelling in _QUOTA_SPELLINGS:
            quota = spelling.quota_of(reason)
            if quota is not None:
                return quota
        return None

    def kind_of(self, reason: str | None) -> UpstreamFailureKind | None:
        if reason is None:
            return None
        kind = self._KINDS.get(reason)
        if kind is not None:
            return kind
        if self.quota_of(reason) is not None:
            return UpstreamFailureKind.QUOTA
        if _is_refusal(reason):
            return UpstreamFailureKind.REFUSAL
        if reason.startswith(self._AUTH_PREFIXES):
            return UpstreamFailureKind.AUTH
        return UpstreamFailureKind.UNKNOWN


#: The reader production uses. Replace this, not its callers, for #1605.
UPSTREAM_FAILURES: UpstreamFailureReader = StreamReasonUpstreamFailureReader()
