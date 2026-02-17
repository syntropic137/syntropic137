"""Execution control commands — pause, resume, cancel, status (HTTP delegation)."""

from __future__ import annotations

import os

import httpx
import typer

from aef_cli._output import console

app = typer.Typer(
    name="control",
    help="Control running executions",
    no_args_is_help=True,
)

DEFAULT_DASHBOARD_URL = "http://localhost:8000"


def _get_dashboard_url(url: str | None) -> str:
    """Get dashboard URL from option or environment."""
    if url:
        return url
    return os.environ.get("AEF_DASHBOARD_URL", DEFAULT_DASHBOARD_URL)


def _handle_connect_error(url: str) -> None:
    console.print(f"[red]Could not connect to dashboard at {url}[/red]")
    console.print("[dim]Make sure the dashboard is running.[/dim]")
    raise typer.Exit(1)


@app.command()
def pause(
    execution_id: str = typer.Argument(..., help="Execution ID to pause"),
    reason: str | None = typer.Option(None, "--reason", "-r", help="Reason for pausing"),
    dashboard_url: str | None = typer.Option(None, "--url", "-u", help="Dashboard API URL"),
) -> None:
    """Pause a running execution at the next yield point."""
    url = _get_dashboard_url(dashboard_url)

    try:
        response = httpx.post(
            f"{url}/api/executions/{execution_id}/pause",
            json={"reason": reason} if reason else None,
            timeout=10.0,
        )

        if response.status_code == 200:
            data = response.json()
            console.print(f"[green]Pause signal sent for execution {execution_id}[/green]")
            console.print(f"  State: {data.get('state', 'unknown')}")
            if data.get("message"):
                console.print(f"  Message: {data['message']}")
        else:
            error = response.json().get("detail", "Unknown error")
            console.print(f"[red]Failed to pause: {error}[/red]")
            raise typer.Exit(1)

    except httpx.ConnectError:
        _handle_connect_error(url)


@app.command()
def resume(
    execution_id: str = typer.Argument(..., help="Execution ID to resume"),
    dashboard_url: str | None = typer.Option(None, "--url", "-u", help="Dashboard API URL"),
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
            console.print(f"[green]Resume signal sent for execution {execution_id}[/green]")
            console.print(f"  State: {data.get('state', 'unknown')}")
        else:
            error = response.json().get("detail", "Unknown error")
            console.print(f"[red]Failed to resume: {error}[/red]")
            raise typer.Exit(1)

    except httpx.ConnectError:
        _handle_connect_error(url)


@app.command()
def cancel(
    execution_id: str = typer.Argument(..., help="Execution ID to cancel"),
    reason: str | None = typer.Option(None, "--reason", "-r", help="Reason for cancelling"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
    dashboard_url: str | None = typer.Option(None, "--url", "-u", help="Dashboard API URL"),
) -> None:
    """Cancel a running or paused execution."""
    url = _get_dashboard_url(dashboard_url)

    if not force:
        confirm = typer.confirm(f"Are you sure you want to cancel execution {execution_id}?")
        if not confirm:
            console.print("[dim]Cancelled.[/dim]")
            raise typer.Exit(0)

    try:
        response = httpx.post(
            f"{url}/api/executions/{execution_id}/cancel",
            json={"reason": reason} if reason else None,
            timeout=10.0,
        )

        if response.status_code == 200:
            data = response.json()
            console.print(f"[green]Cancel signal sent for execution {execution_id}[/green]")
            console.print(f"  State: {data.get('state', 'unknown')}")
        else:
            error = response.json().get("detail", "Unknown error")
            console.print(f"[red]Failed to cancel: {error}[/red]")
            raise typer.Exit(1)

    except httpx.ConnectError:
        _handle_connect_error(url)


@app.command()
def status(
    execution_id: str = typer.Argument(..., help="Execution ID to check"),
    dashboard_url: str | None = typer.Option(None, "--url", "-u", help="Dashboard API URL"),
) -> None:
    """Get current execution control state."""
    url = _get_dashboard_url(dashboard_url)

    state_colors = {
        "pending": "dim",
        "running": "blue",
        "paused": "yellow",
        "cancelled": "orange3",
        "completed": "green",
        "failed": "red",
    }

    try:
        response = httpx.get(
            f"{url}/api/executions/{execution_id}/state",
            timeout=10.0,
        )

        if response.status_code == 200:
            data = response.json()
            state = data.get("state", "unknown")
            color = state_colors.get(state, "white")

            console.print(f"Execution: {execution_id}")
            console.print(f"State: [{color}]{state}[/{color}]")
        else:
            console.print("[red]Failed to get status[/red]")
            raise typer.Exit(1)

    except httpx.ConnectError:
        _handle_connect_error(url)
