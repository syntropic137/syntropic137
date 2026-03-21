"""Rich formatting helpers for CLI output."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

from rich.console import Console
from rich.table import Table

console = Console()


def format_cost(cost: Decimal | str | float) -> str:
    """Format a cost value for display."""
    d = Decimal(str(cost))
    if d < Decimal("0.01"):
        return f"${d:.4f}"
    return f"${d:.2f}"


def format_tokens(tokens: int) -> str:
    """Format a token count for display."""
    if tokens >= 1_000_000:
        return f"{tokens / 1_000_000:.1f}M"
    if tokens >= 1_000:
        return f"{tokens / 1_000:.1f}K"
    return str(tokens)


def print_error(message: str) -> None:
    """Print a red error message."""
    console.print(f"[bold red]Error:[/bold red] {message}")


def print_success(message: str) -> None:
    """Print a green success message."""
    console.print(f"[green]{message}[/green]")


def format_duration(ms: float) -> str:
    """Convert milliseconds to human-readable duration (e.g., '1.2s', '2m 15s', '1h 30m')."""
    if ms < 1000:
        return f"{ms:.0f}ms"
    seconds = ms / 1000
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    if minutes < 60:
        return f"{minutes}m {secs}s" if secs else f"{minutes}m"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h {mins}m" if mins else f"{hours}h"


def format_timestamp(iso: str | None) -> str:
    """Convert ISO timestamp to local time string (e.g., 'Mar 16 14:30')."""
    if not iso:
        return "-"
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        local_dt = dt.astimezone()
        return local_dt.strftime("%b %d %H:%M")
    except (ValueError, TypeError):
        return iso


def format_breakdown(
    breakdown: dict[str, str],
    title: str,
    value_fn: Callable[[str], str] | None = None,
) -> Table:
    """Render a cost/token breakdown dict as a Rich sub-table."""
    table = Table(title=title, show_edge=False, pad_edge=False)
    table.add_column("Key", style="cyan")
    table.add_column("Value", justify="right")
    for key, value in breakdown.items():
        table.add_row(key, value_fn(value) if value_fn else str(value))
    return table


def status_style(status: str) -> str:
    """Return a Rich style string for a status value."""
    return {
        "active": "green",
        "paused": "yellow",
        "deleted": "red",
        "completed": "green",
        "failed": "red",
        "running": "blue",
        "pending": "dim",
    }.get(status, "")
