"""Rich formatting helpers for CLI output."""

from __future__ import annotations

from decimal import Decimal

from rich.console import Console

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
