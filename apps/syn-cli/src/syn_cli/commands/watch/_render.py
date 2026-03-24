"""SSE event rendering and parsing for watch commands."""

from __future__ import annotations

import json
from typing import Any

import typer

from syn_cli._output import console, format_cost, format_timestamp, status_style

app = typer.Typer(
    name="watch",
    help="Watch live execution or activity streams",
    no_args_is_help=True,
)


def parse_sse_line(line: str) -> dict[str, object] | None:
    """Parse a single SSE data line into a dict, or None if not a data line."""
    if not line.startswith("data: "):
        return None
    raw = line[6:].strip()
    if not raw:
        return None
    try:
        parsed: dict[str, object] = json.loads(raw)
        return parsed
    except json.JSONDecodeError:
        return None


_EVENT_FORMATS: dict[str, tuple[str, str]] = {
    "WorkflowExecutionStarted": ("▶ started", "green"),
    "WorkflowCompleted": ("✓ completed", "green"),
    "WorkflowFailed": ("✗ failed", "red"),
    "PhaseStarted": ("→ phase", "blue"),
    "PhaseCompleted": ("✓ phase", "blue"),
}


def _event_suffix(event_type: str, data: dict[str, Any]) -> str:
    """Compute display suffix for known event types."""
    if event_type == "WorkflowCompleted":
        return f"  {format_cost(data.get('total_cost_usd') or '0')}"
    if event_type == "WorkflowFailed":
        return f"  {str(data.get('error_message') or '')[:60]}"
    return ""


def _event_id(event_type: str, data: dict[str, Any]) -> str:
    """Determine the display identifier for an event."""
    if event_type in ("PhaseStarted", "PhaseCompleted"):
        return str(data.get("phase_name", ""))
    return str(data.get("execution_id", ""))[:12]


def render_event(frame: dict[str, object]) -> None:
    """Render an SSE event frame to the console."""
    event_type = str(frame.get("event_type", ""))
    data = frame.get("data")
    if not isinstance(data, dict):
        data = {}
    ts = format_timestamp(str(frame.get("timestamp", "")))

    fmt = _EVENT_FORMATS.get(event_type)
    if fmt:
        label, color = fmt
        console.print(
            f"[dim]{ts}[/dim]  [{color}]{label}[/{color}]  "
            f"{_event_id(event_type, data)}{_event_suffix(event_type, data)}"
        )
    elif event_type == "SessionTokensRecorded":
        tokens = data.get("total_tokens", 0)
        console.print(
            f"[dim]{ts}[/dim]  [dim]tokens {tokens}  {format_cost(data.get('cost_usd') or '0')}[/dim]"
        )
    elif event_type:
        status = str(data.get("status", ""))
        style = status_style(status)
        tail = f"  [{style}]{status}[/{style}]" if status and style else ""
        console.print(f"[dim]{ts}[/dim]  [dim]{event_type}[/dim]{tail}")
