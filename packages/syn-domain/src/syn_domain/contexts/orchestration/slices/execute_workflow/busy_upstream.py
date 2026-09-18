"""When a failed agent phase gets another attempt, and how long it waits (#1303).

A phase that ends because the model provider was BUSY has not told us anything
about the change, the workspace or the platform. The request was well-formed;
the upstream simply had no capacity for it this second:

    Agent failed: codex reported: Selected model is at capacity.
    Please try a different model. (phase=verify, exit_code=1)

That failure used to end the execution, discarding every phase that had already
completed and been paid for - twice in one window, $18.63, both at `verify`,
which is the third of four phases. The blip lasts seconds; the loss is total.

Two ways to get this wrong, and they pull in opposite directions:

  - Retry too much. A second attempt at a login that is not valid, a prompt the
    provider refused, or a stream nobody can parse will fail exactly the same
    way, having spent the phase's budget again. One loss becomes several. So
    the signatures below are a closed list of things an upstream says about
    ITSELF, never about the request.
  - Hide a permanent failure. A retry that runs out of attempts and then
    reports something other than the original cause is worse than no retry:
    the execution still fails, but the reason it failed is now a story about
    retrying. So this module decides only whether to go again. It never
    touches, wraps or replaces the reason, and the caller fails with exactly
    the reason it already had.

DELIBERATELY NOT HERE: HTTP 5xx / `api_error`. A server error may be transient
and may be a persistent rejection wearing a 500, and nothing in the message
distinguishes them. The class this exists for - "we are full, come back" - is
one the upstream states plainly, so the list only needs the plain statements.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

#: Lowercase fragments that appear in a reason ONLY when the upstream is
#: reporting its own capacity. Matched against the reason as the rest of the
#: system already spells it, which is the one string both harnesses converge
#: on: codex's own words, forwarded by `CodexStreamProcessor._note_stream_fault`
#: as "codex reported: ...", and claude's, normalised by `api_error_label` into
#: "API overloaded (HTTP 529)" / "Rate limited (HTTP 429)". Both providers are
#: covered because both fail this way and the loss is identical either way.
_BUSY_UPSTREAM_SIGNATURES: tuple[str, ...] = (
    # codex: "Selected model is at capacity. Please try a different model."
    "at capacity",
    # claude: API_ERROR_LABELS[OVERLOADED], and the raw Anthropic error type
    # for the paths that report a body rather than a label.
    "api overloaded",
    "overloaded_error",
    # claude: API_ERROR_LABELS[RATE_LIMIT], plus the raw type and the phrasing
    # a provider uses in prose ("rate limit exceeded").
    "rate limited",
    "rate limit",
    "rate_limit_error",
)


def _upstream_was_busy(reason: str | None) -> bool:
    """Whether ``reason`` is the upstream reporting its own capacity."""
    if not reason:
        return False
    return any(signature in reason.lower() for signature in _BUSY_UPSTREAM_SIGNATURES)


@dataclass(frozen=True)
class UpstreamRetryPolicy:
    """How many times a phase may re-attempt a busy upstream, and when.

    One question, asked once per failed attempt: go again, or not? The caller
    learns nothing about which failures qualify, how many attempts remain or
    how long the wait was - change any of that here and no caller changes.
    """

    #: Total attempts for one phase, the first one included. Bounded, and
    #: small: capacity that has not returned after two backoffs is not the
    #: blip this exists for, and the phases downstream have their own budget.
    max_attempts: int = 3
    #: Doubles per attempt: 5s, then 10s. Long enough for a queue to drain,
    #: short enough that a phase measured in minutes does not notice.
    base_delay_seconds: float = 5.0

    async def wait_before_retry(self, *, reason: str | None, attempt: int) -> bool:
        """Sleep out the backoff and report whether attempt ``attempt`` gets a successor.

        ``attempt`` is 1-based: the value passed is the attempt that just
        failed with ``reason``.

        False means this failure is final and the caller must report ``reason``
        as it stands. It says nothing about WHY it is final - a genuine error
        and a spent budget both end the run the same way, with the same cause,
        and a caller that branched on the difference would be inventing one.
        """
        if attempt >= self.max_attempts or not _upstream_was_busy(reason):
            return False
        await asyncio.sleep(self.base_delay_seconds * 2 ** (attempt - 1))
        return True
