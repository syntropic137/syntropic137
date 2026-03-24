"""Execution control commands — pause, resume, cancel, status, stop."""

from __future__ import annotations

from typing import Annotated

import typer

from syn_cli._output import console
from syn_cli.commands._api_helpers import api_get, api_post

app = typer.Typer(
    name="control",
    help="Control running executions",
    no_args_is_help=True,
)

_STATE_COLORS: dict[str, str] = {
    "pending": "dim",
    "running": "blue",
    "paused": "yellow",
    "cancelled": "orange3",
    "interrupted": "orange3",
    "completed": "green",
    "failed": "red",
}


@app.command()
def pause(
    execution_id: Annotated[str, typer.Argument(help="Execution ID to pause")],
    reason: Annotated[str | None, typer.Option("--reason", "-r", help="Reason for pausing")] = None,
) -> None:
    """Pause a running execution at the next yield point."""
    data = api_post(
        f"/api/executions/{execution_id}/pause",
        json={"reason": reason} if reason else None,
    )

    console.print(f"[green]Pause signal sent for execution {execution_id}[/green]")
    console.print(f"  State: {data.get('state', 'unknown')}")
    if data.get("message"):
        console.print(f"  Message: {data['message']}")


@app.command()
def resume(
    execution_id: Annotated[str, typer.Argument(help="Execution ID to resume")],
) -> None:
    """Resume a paused execution."""
    data = api_post(f"/api/executions/{execution_id}/resume")

    console.print(f"[green]Resume signal sent for execution {execution_id}[/green]")
    console.print(f"  State: {data.get('state', 'unknown')}")


@app.command()
def cancel(
    execution_id: Annotated[str, typer.Argument(help="Execution ID to cancel")],
    reason: Annotated[
        str | None, typer.Option("--reason", "-r", help="Reason for cancelling")
    ] = None,
    force: Annotated[bool, typer.Option("--force", "-f", help="Skip confirmation prompt")] = False,
) -> None:
    """Cancel a running or paused execution."""
    if not force:
        confirm = typer.confirm(f"Are you sure you want to cancel execution {execution_id}?")
        if not confirm:
            console.print("[dim]Cancelled.[/dim]")
            raise typer.Exit(0)

    data = api_post(
        f"/api/executions/{execution_id}/cancel",
        json={"reason": reason} if reason else None,
    )

    console.print(f"[green]Cancel signal sent for execution {execution_id}[/green]")
    console.print(f"  State: {data.get('state', 'unknown')}")


def _render_interrupted_detail(execution_id: str) -> None:
    """Fetch and display additional context for interrupted executions."""
    try:
        detail = api_get(f"/api/executions/{execution_id}")
        if detail.get("error_message"):
            console.print(f"  Reason: {detail['error_message']}")
        if detail.get("completed_at"):
            console.print(f"  Interrupted at: {detail['completed_at']}")
        if detail.get("git_sha"):
            console.print(f"  Git SHA: {detail['git_sha']}")
    except SystemExit:
        pass


@app.command()
def status(
    execution_id: Annotated[str, typer.Argument(help="Execution ID to check")],
) -> None:
    """Get current execution control state."""
    data = api_get(f"/api/executions/{execution_id}/state")
    state = data.get("state", "unknown")
    color = _STATE_COLORS.get(state, "white")

    console.print(f"Execution: {execution_id}")
    console.print(f"State: [{color}]{state}[/{color}]")

    if state == "interrupted":
        _render_interrupted_detail(execution_id)


@app.command()
def inject(
    execution_id: Annotated[str, typer.Argument(help="Execution ID")],
    message: Annotated[str, typer.Option("--message", "-m", help="Message to inject")],
) -> None:
    """Inject a message into a running execution."""
    api_post(f"/executions/{execution_id}/inject", json={"message": message})
    console.print(f"[green]Message injected into execution {execution_id}[/green]")


@app.command()
def stop(
    execution_id: Annotated[str, typer.Argument(help="Execution ID to stop")],
    reason: Annotated[
        str | None, typer.Option("--reason", "-r", help="Reason for stopping")
    ] = None,
    force: Annotated[bool, typer.Option("--force", "-f", help="Skip confirmation prompt")] = False,
) -> None:
    """Forcefully stop a running execution via SIGINT.

    Sends a cancel signal that causes the engine to interrupt the Claude CLI
    process via SIGINT and capture partial output as an interrupted execution.
    """
    stop_reason = reason or "Stopped by user via syn stop"

    if not force:
        confirm = typer.confirm(f"Are you sure you want to stop execution {execution_id}?")
        if not confirm:
            console.print("[dim]Aborted.[/dim]")
            raise typer.Exit(0)

    data = api_post(
        f"/api/executions/{execution_id}/cancel",
        json={"reason": stop_reason},
    )

    console.print(f"[orange3]Stop signal sent for execution {execution_id}[/orange3]")
    console.print(f"  State: {data.get('state', 'unknown')}")
    if data.get("message"):
        console.print(f"  Message: {data['message']}")
