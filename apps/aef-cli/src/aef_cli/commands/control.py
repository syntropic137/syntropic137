"""CLI commands for execution control."""

from __future__ import annotations

import httpx
import typer
from rich.console import Console

app = typer.Typer(help="Control running executions")
console = Console()

# Default dashboard URL - can be overridden via environment or option
DEFAULT_DASHBOARD_URL = "http://localhost:8000"


def _get_dashboard_url(url: str | None) -> str:
    """Get dashboard URL from option or environment."""
    import os

    if url:
        return url
    return os.environ.get("AEF_DASHBOARD_URL", DEFAULT_DASHBOARD_URL)


@app.command()
def pause(
    execution_id: str = typer.Argument(..., help="Execution ID to pause"),
    reason: str | None = typer.Option(
        None, "--reason", "-r", help="Reason for pausing"
    ),
    dashboard_url: str | None = typer.Option(
        None, "--url", "-u", help="Dashboard API URL"
    ),
) -> None:
    """Pause a running execution.

    The execution will pause at the next yield point (after the current tool completes).
    """
    url = _get_dashboard_url(dashboard_url)

    try:
        response = httpx.post(
            f"{url}/api/executions/{execution_id}/pause",
            json={"reason": reason} if reason else None,
            timeout=10.0,
        )

        if response.status_code == 200:
            data = response.json()
            console.print(f"[green]✓[/green] Pause signal sent for execution {execution_id}")
            console.print(f"  State: {data.get('state', 'unknown')}")
            if data.get("message"):
                console.print(f"  Message: {data['message']}")
        else:
            error = response.json().get("detail", "Unknown error")
            console.print(f"[red]✗[/red] Failed to pause: {error}", style="red")
            raise typer.Exit(1) from None

    except httpx.ConnectError:
        console.print(
            f"[red]✗[/red] Could not connect to dashboard at {url}",
            style="red",
        )
        console.print("  Make sure the dashboard is running.", style="dim")
        raise typer.Exit(1) from None


@app.command()
def resume(
    execution_id: str = typer.Argument(..., help="Execution ID to resume"),
    dashboard_url: str | None = typer.Option(
        None, "--url", "-u", help="Dashboard API URL"
    ),
) -> None:
    """Resume a paused execution."""
    url = _get_dashboard_url(dashboard_url)

    try:
        response = httpx.post(
            f"{url}/api/executions/{execution_id}/resume",
            timeout=10.0,
        )

        if response.status_code == 200:
            data = response.json()
            console.print(f"[green]✓[/green] Resume signal sent for execution {execution_id}")
            console.print(f"  State: {data.get('state', 'unknown')}")
        else:
            error = response.json().get("detail", "Unknown error")
            console.print(f"[red]✗[/red] Failed to resume: {error}", style="red")
            raise typer.Exit(1) from None

    except httpx.ConnectError:
        console.print(
            f"[red]✗[/red] Could not connect to dashboard at {url}",
            style="red",
        )
        raise typer.Exit(1) from None


@app.command()
def cancel(
    execution_id: str = typer.Argument(..., help="Execution ID to cancel"),
    reason: str | None = typer.Option(
        None, "--reason", "-r", help="Reason for cancelling"
    ),
    force: bool = typer.Option(
        False, "--force", "-f", help="Skip confirmation prompt"
    ),
    dashboard_url: str | None = typer.Option(
        None, "--url", "-u", help="Dashboard API URL"
    ),
) -> None:
    """Cancel a running or paused execution.

    The execution will terminate with cleanup.
    """
    url = _get_dashboard_url(dashboard_url)

    # Confirm unless force flag is set
    if not force:
        confirm = typer.confirm(
            f"Are you sure you want to cancel execution {execution_id}?"
        )
        if not confirm:
            console.print("Cancelled.", style="dim")
            raise typer.Exit(0)

    try:
        response = httpx.post(
            f"{url}/api/executions/{execution_id}/cancel",
            json={"reason": reason} if reason else None,
            timeout=10.0,
        )

        if response.status_code == 200:
            data = response.json()
            console.print(f"[green]✓[/green] Cancel signal sent for execution {execution_id}")
            console.print(f"  State: {data.get('state', 'unknown')}")
        else:
            error = response.json().get("detail", "Unknown error")
            console.print(f"[red]✗[/red] Failed to cancel: {error}", style="red")
            raise typer.Exit(1) from None

    except httpx.ConnectError:
        console.print(
            f"[red]✗[/red] Could not connect to dashboard at {url}",
            style="red",
        )
        raise typer.Exit(1) from None


@app.command()
def status(
    execution_id: str = typer.Argument(..., help="Execution ID to check"),
    dashboard_url: str | None = typer.Option(
        None, "--url", "-u", help="Dashboard API URL"
    ),
) -> None:
    """Get current execution control state."""
    url = _get_dashboard_url(dashboard_url)

    try:
        response = httpx.get(
            f"{url}/api/executions/{execution_id}/state",
            timeout=10.0,
        )

        if response.status_code == 200:
            data = response.json()
            state = data.get("state", "unknown")

            # Color-code the state
            state_colors = {
                "pending": "dim",
                "running": "blue",
                "paused": "yellow",
                "cancelled": "orange3",
                "completed": "green",
                "failed": "red",
                "unknown": "dim",
            }
            color = state_colors.get(state, "white")

            console.print(f"Execution: {execution_id}")
            console.print(f"State: [{color}]{state}[/{color}]")
        else:
            console.print("[red]✗[/red] Failed to get status", style="red")
            raise typer.Exit(1) from None

    except httpx.ConnectError:
        console.print(
            f"[red]✗[/red] Could not connect to dashboard at {url}",
            style="red",
        )
        raise typer.Exit(1) from None
