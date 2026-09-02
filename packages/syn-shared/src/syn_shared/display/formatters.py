"""Pure formatter functions for human-readable values.

These produce the strings exposed as ``*_display`` fields on API responses so
all clients (dashboard, CLI, future UIs) share the same rendering.

See: docs/adrs/ADR-064-observability-monitor-ui.md
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal

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


def _parse_timestamp(value: datetime | str | None) -> datetime | None:
    """Parse an ISO 8601 string or pass through an existing datetime.

    Handles the trailing ``Z`` suffix (RFC 3339) that ``fromisoformat`` rejects
    on Python <3.11. Returns ``None`` for anything unparseable rather than
    raising, since a malformed timestamp is exactly as "unknown" as a missing
    one to the caller.
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
        return None


def compute_duration_seconds(
    started_at: datetime | str | None,
    *,
    now: datetime | str | None = None,
) -> float | None:
    """Elapsed time for something that is still running: ``now - started_at``.

    The single definition of "how long has this been running" shared by the
    execution and session read paths (``executions/queries.py`` and
    ``sessions.py``), so the two surfaces can no longer disagree about a phase
    or session that is live at the moment of the read.

    Terminal phases/sessions are NOT this function's job -- they keep whatever
    duration was recorded at completion. This only covers the gap where no
    completion has happened yet, so there is nothing stored to read: without
    it, a running phase reports a duration frozen at whatever it was when it
    started (or ``None``), indistinguishable from a hang. That ambiguity got
    six healthy workflow runs cancelled on 2026-09-01 after a frozen duration
    reading was misread as one.

    Returns ``None`` when ``started_at`` is missing or unparseable -- a
    genuinely unknown duration must never collapse to ``0.0``, which looks
    exactly like a real measurement.
    """
    started = _parse_timestamp(started_at)
    if started is None:
        return None
    # `now` is parsed the same way as `started_at` so a caller closing out a
    # cancelled phase can pass the event's timestamp directly. Without this the
    # elapsed time of a cancelled phase would be measured against the wall
    # clock and keep growing forever after the run ended.
    reference = _parse_timestamp(now) if now is not None else datetime.now(UTC)
    if reference is None:
        return None
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    return max((reference - started).total_seconds(), 0.0)


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
