"""Pure functions for the values every read surface reports.

Mostly formatters: these produce the strings exposed as ``*_display`` fields on
API responses so all clients (dashboard, CLI, future UIs) share the same
rendering. ``resolve_duration_seconds`` is here for the same reason one level
down -- the surfaces have to agree on what a duration IS before they can agree
on how it reads.

See: docs/adrs/ADR-064-observability-monitor-ui.md
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from decimal import Decimal

logger = logging.getLogger(__name__)

EM_DASH = "\u2014"


def format_tokens(n: int | None) -> str:
    """Format a token count with k/M suffixes.

    Examples: ``0 -> "0"``, ``742 -> "742"``, ``1237 -> "1.2k"``,
    ``1_500_000 -> "1.5M"``. ``None`` renders as an em dash.
    """
    if n is None:
        return EM_DASH
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


UNPRICED = "unpriced"
"""Rendered when nothing in the total could be priced."""


def _format_known_cost(value: Decimal) -> str:
    """Render a cost that is known to be complete."""
    if value < 0:
        return "-" + _format_known_cost(-value)
    if value == 0:
        return "$0.00"
    if value < Decimal("0.01"):
        return "<$0.01"
    if value >= Decimal("1000"):
        return f"${value / 1000:.1f}k"
    return f"${value:.2f}"


def format_cost(usd: float | Decimal | int | None, unpriced_count: int = 0) -> str:
    """Format a USD cost, saying so when the figure is incomplete.

    Sub-cent values render as ``"<$0.01"`` (we don't pretend cents below the
    smallest payable unit are meaningful). Values at or above ``$1000`` use the
    ``$1.2k`` style. Negative values render with a leading minus.

    ``unpriced_count`` is how many observations carried no usable rate and so
    contributed nothing to ``usd``. It is not decoration: without it a total of
    zero reads as "this was free" when it actually means "we could not price
    this", which is exactly how unpriced codex runs rendered as ``$0.00`` all
    the way to the dashboard (issue #890, ADR-067 D5). A non-zero count with a
    non-zero total means the figure is a real lower bound, not the total.

    Mirrors ``formatCostWithCoverage`` in ``apps/syn-cli-node/src/output/format.ts``
    so the API and the CLI render the same three states.

    USD-only for now. Revisit when multi-currency arrives.
    """
    if usd is None:
        return EM_DASH
    value = Decimal(str(usd)) if not isinstance(usd, Decimal) else usd
    if unpriced_count <= 0:
        return _format_known_cost(value)
    if value <= 0:
        return UNPRICED
    return f">={_format_known_cost(value)} (partial)"


def format_duration_seconds(seconds: float | int | None) -> str:
    """Format a duration in seconds.

    Examples: ``None -> em dash``, ``0.4 -> "<1s"``, ``5 -> "5s"``,
    ``134.2 -> "2m 14s"``, ``3725 -> "1h 2m"``.
    """
    if seconds is None:
        return EM_DASH
    if seconds < 1:
        return "<1s"
    total = int(seconds)
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m {secs}s" if secs else f"{minutes}m"
    hours, mins = divmod(minutes, 60)
    return f"{hours}h {mins}m" if mins else f"{hours}h"


#: Statuses meaning the work has not begun. Nothing has elapsed, so there is
#: no duration to report -- not zero, unknown.
_NOT_STARTED_STATUSES = frozenset({"pending", "not_started"})

#: Statuses meaning the work is still going. The duration is whatever has
#: elapsed at the instant of the read, which is why it must not be stored.
#: ``paused`` counts: the reported figure is wall-clock time since the start,
#: exactly as it is for a finished run whose span also covers its pauses.
_IN_FLIGHT_STATUSES = frozenset({"running", "paused"})


def _parse_timestamp(value: datetime | str | None) -> datetime | None:
    """Parse an ISO 8601 string or pass through an existing datetime.

    Handles the trailing ``Z`` suffix (RFC 3339) that ``fromisoformat`` rejects
    on Python <3.11. Returns ``None`` for anything unparseable -- and says so in
    the log, because a stored timestamp that will not parse is corruption, not
    an absent value, and the two are otherwise indistinguishable downstream.
    """
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        logger.warning("Unparseable timestamp %r; reporting the duration as unknown", value)
        return None


def _as_utc(value: datetime) -> datetime:
    """Attach UTC to a naive datetime; every timestamp we store is UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _elapsed_seconds(
    started_at: datetime | str | None,
    ended_at: datetime | str | None,
) -> float | None:
    """Seconds between two instants, or ``None`` if that span is not measurable.

    A negative span means the two timestamps disagree about the order of events
    -- clock skew, or a future ``started_at``. Reporting that as ``0.0`` would
    turn a broken clock into a confident measurement of "no time at all", so it
    is reported as unknown instead, loudly.
    """
    started = _parse_timestamp(started_at)
    ended = _parse_timestamp(ended_at)
    if started is None or ended is None:
        return None
    seconds = (_as_utc(ended) - _as_utc(started)).total_seconds()
    if seconds < 0:
        logger.warning(
            "Duration of %.3fs is negative (started_at=%r, ended_at=%r); "
            "reporting it as unknown rather than 0.0",
            seconds,
            started_at,
            ended_at,
        )
        return None
    return seconds


def resolve_duration_seconds(
    status: str | None,
    *,
    started_at: datetime | str | None,
    ended_at: datetime | str | None = None,
    recorded_seconds: float | None = None,
    now: datetime | str | None = None,
) -> float | None:
    """How long this ran, given where it is in its lifecycle.

    The single answer to that question for every read surface -- execution
    list, execution detail, phases, sessions, repo and system activity. They
    each used to decide it for themselves and so disagreed about the same run
    at the same instant; a caller now says what it knows and this decides.

    Callers pass what they have:

    - ``status``   -- lifecycle status, matched case-insensitively.
    - ``started_at`` / ``ended_at`` -- ISO strings or datetimes.
    - ``recorded_seconds`` -- a duration already measured elsewhere (a phase
      completion event, Lane 2 telemetry). Preferred over the timestamp span
      once the work has finished, because it was measured at the source.
    - ``now`` -- the reference instant for work still in flight. Defaults to
      the wall clock, which is what the read paths want; pass it explicitly to
      close out a run at the moment it ended.

    Three lifecycle cases, and one rule for all of them:

    - not started -> ``None``. Nothing has elapsed.
    - in flight   -> ``now - started_at``, computed at every read. Anything
      stored would be frozen at the value it had when the phase began, which
      is indistinguishable from a hang: that reading got six healthy workflow
      runs cancelled on 2026-09-01.
    - finished    -> ``recorded_seconds``, else ``ended_at - started_at``.

    An unrecognised status is treated as finished, so a new status added
    elsewhere can only ever under-report (``None``) rather than invent a live
    duration that grows forever.

    ``None`` means genuinely unknown and NEVER ``0.0``. That collapse is the
    whole defect: ``0.0`` renders as a real measurement of an instantaneous
    run, so a reader cannot tell a phase that took no time from one nobody
    measured.
    """
    lifecycle = (status or "").strip().lower()
    if lifecycle in _NOT_STARTED_STATUSES:
        return None
    if lifecycle in _IN_FLIGHT_STATUSES:
        return _elapsed_seconds(started_at, now if now is not None else datetime.now(UTC))
    if recorded_seconds is not None:
        return recorded_seconds
    return _elapsed_seconds(started_at, ended_at)


_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def format_phase(phase_id: str | None) -> str | None:
    """Render a phase id as a human-readable label.

    Slug ids title-case: ``"research_phase" -> "Research Phase"``,
    ``"fix-bug" -> "Fix Bug"``, ``"detect" -> "Detect"``.

    UUID ids (workflow phase runtime identifiers) render as the first hex
    segment with a ``Phase`` prefix: ``"39574120-df6e-..." -> "Phase 39574120"``,
    since title-casing a UUID produces garbage and no slug is available at this
    layer. Callers with workflow context should prefer the real phase name.

    Returns ``None`` when input is ``None`` so callers can pass-through.
    """
    if phase_id is None:
        return None
    raw = phase_id.strip()
    if not raw:
        return raw
    if _UUID_RE.match(raw):
        return f"Phase {raw.split('-', 1)[0]}"
    words = raw.replace("_", " ").replace("-", " ").split()
    return " ".join(word.capitalize() for word in words) if words else raw


def format_model_compact(model: str | None) -> str | None:
    """Render a Claude model id as a compact display name.

    ``"claude-sonnet-4-6" -> "Sonnet 4.6"``,
    ``"claude-opus-4-20250514" -> "Opus 4 (20250514)"`` is intentionally not
    done; we only collapse the well-known ``claude-{family}-{version...}`` shape
    so unknown ids round-trip unchanged.

    Returns ``None`` when input is ``None`` so callers can pass-through.
    """
    if model is None:
        return None
    raw = model.strip()
    if not raw:
        return raw
    if not raw.startswith("claude-"):
        return raw
    parts = raw[len("claude-") :].split("-")
    if len(parts) < 2:
        return raw
    family = parts[0]
    version_parts = parts[1:]
    # Only collapse short numeric segments (single major plus optional minor).
    # Dated suffixes like "20250514" or any non-numeric segment leave the id
    # unchanged so we never mangle published model identifiers.
    if not all(p.isdigit() and len(p) <= 2 for p in version_parts):
        return raw
    version = ".".join(version_parts)
    return f"{family.title()} {version}"


def format_repos(repos: list[str] | tuple[str, ...] | None) -> str | None:
    """Render a list of ``owner/repo`` slugs as a compact label.

    One repo: just the repo name (``"acme/foo" -> "foo"``).
    Multiple: first repo + ``+N`` (``["acme/foo", "acme/bar"] -> "foo +1"``).
    Empty or ``None`` returns ``None``.
    """
    if not repos:
        return None
    items = [r.strip() for r in repos if r and r.strip()]
    if not items:
        return None
    first = items[0].split("/", 1)[-1] or items[0]
    if len(items) == 1:
        return first
    return f"{first} +{len(items) - 1}"
