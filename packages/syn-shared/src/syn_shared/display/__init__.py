"""Canonical human-readable formatters shared across the platform.

The CLI, dashboard, and any future UIs all read the same ``*_display`` strings
that the API produces from these functions, so that humans see consistent
formatting regardless of where they look.

Anything locale- or time-of-render-dependent (e.g. relative time, locale
timestamps) stays client-side. Server returns ISO 8601 UTC; clients format with
``Intl.DateTimeFormat`` or equivalent.

See: docs/adrs/ADR-064-observability-monitor-ui.md
"""

from __future__ import annotations

from syn_shared.display.formatters import (
    format_cost,
    format_duration_seconds,
    format_model_compact,
    format_phase,
    format_tokens,
)

__all__ = [
    "format_cost",
    "format_duration_seconds",
    "format_model_compact",
    "format_phase",
    "format_tokens",
]
