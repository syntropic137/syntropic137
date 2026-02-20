"""Execution control commands — pause, resume, cancel, status (HTTP delegation)."""

from __future__ import annotations

import os

import httpx
import typer

from syn_cli._output import console

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
    return os.environ.get("SYN_DASHBOARD_URL", DEFAULT_DASHBOARD_URL)


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
        "interrupted": "orange3",
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

            # For interrupted state, fetch full detail for additional context
            if state == "interrupted":
                detail_response = httpx.get(
                    f"{url}/api/executions/{execution_id}",
                    timeout=10.0,
                )
                if detail_response.status_code == 200:
                    detail = detail_response.json()
                    if detail.get("error_message"):
                        console.print(f"  Reason: {detail['error_message']}")
                    if detail.get("completed_at"):
                        console.print(f"  Interrupted at: {detail['completed_at']}")
                    if detail.get("git_sha"):
                        console.print(f"  Git SHA: {detail['git_sha']}")
        else:
            console.print("[red]Failed to get status[/red]")
            raise typer.Exit(1)

    except httpx.ConnectError:
        _handle_connect_error(url)


@app.command()
def stop(
    execution_id: str = typer.Argument(..., help="Execution ID to stop"),
    reason: str | None = typer.Option(None, "--reason", "-r", help="Reason for stopping"),
    dashboard_url: str | None = typer.Option(None, "--url", "-u", help="Dashboard API URL"),
) -> None:
    """Forcefully stop a running execution (no confirmation prompt).

    Sends a cancel signal that causes the engine to interrupt the Claude CLI
    process via SIGINT and capture partial output as an interrupted execution.
    """
    url = _get_dashboard_url(dashboard_url)
    stop_reason = reason or "Stopped by user via aef stop"

    try:
        response = httpx.post(
            f"{url}/api/executions/{execution_id}/cancel",
            json={"reason": stop_reason},
            timeout=10.0,
        )

        if response.status_code == 200:
            data = response.json()
            console.print(f"[orange3]Stop signal sent for execution {execution_id}[/orange3]")
            console.print(f"  State: {data.get('state', 'unknown')}")
            if data.get("message"):
                console.print(f"  Message: {data['message']}")
        else:
            error = response.json().get("detail", "Unknown error")
            console.print(f"[red]Failed to stop: {error}[/red]")
            raise typer.Exit(1)

    except httpx.ConnectError:
        _handle_connect_error(url)
