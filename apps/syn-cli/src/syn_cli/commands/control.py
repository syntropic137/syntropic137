"""Execution control commands — pause, resume, cancel, status, stop."""

from __future__ import annotations

from typing import Annotated

import typer

from syn_cli._output import console, print_error
from syn_cli.client import get_client

app = typer.Typer(
    name="control",
    help="Control running executions",
    no_args_is_help=True,
)


def _handle_connect_error() -> None:
    from syn_cli.client import get_api_url

    print_error(f"Could not connect to API at {get_api_url()}")
    console.print("[dim]Make sure the API server is running.[/dim]")
    raise typer.Exit(1)


@app.command()
def pause(
    execution_id: Annotated[str, typer.Argument(help="Execution ID to pause")],
    reason: Annotated[str | None, typer.Option("--reason", "-r", help="Reason for pausing")] = None,
) -> None:
    """Pause a running execution at the next yield point."""
    try:
        with get_client() as client:
            resp = client.post(
                f"/api/executions/{execution_id}/pause",
                json={"reason": reason} if reason else None,
            )
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code != 200:
        error = resp.json().get("detail", "Unknown error")
        console.print(f"[red]Failed to pause: {error}[/red]")
        raise typer.Exit(1)

    data = resp.json()
    console.print(f"[green]Pause signal sent for execution {execution_id}[/green]")
    console.print(f"  State: {data.get('state', 'unknown')}")
    if data.get("message"):
        console.print(f"  Message: {data['message']}")


@app.command()
def resume(
    execution_id: Annotated[str, typer.Argument(help="Execution ID to resume")],
) -> None:
    """Resume a paused execution."""
    try:
        with get_client() as client:
            resp = client.post(f"/api/executions/{execution_id}/resume")
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code != 200:
        error = resp.json().get("detail", "Unknown error")
        console.print(f"[red]Failed to resume: {error}[/red]")
        raise typer.Exit(1)

    data = resp.json()
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

    try:
        with get_client() as client:
            resp = client.post(
                f"/api/executions/{execution_id}/cancel",
                json={"reason": reason} if reason else None,
            )
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code != 200:
        error = resp.json().get("detail", "Unknown error")
        console.print(f"[red]Failed to cancel: {error}[/red]")
        raise typer.Exit(1)

    data = resp.json()
    console.print(f"[green]Cancel signal sent for execution {execution_id}[/green]")
    console.print(f"  State: {data.get('state', 'unknown')}")


@app.command()
def status(
    execution_id: Annotated[str, typer.Argument(help="Execution ID to check")],
) -> None:
    """Get current execution control state."""
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
        with get_client() as client:
            resp = client.get(f"/api/executions/{execution_id}/state")

            if resp.status_code != 200:
                print_error("Failed to get status")
                raise typer.Exit(1)

            data = resp.json()
            state = data.get("state", "unknown")
            color = state_colors.get(state, "white")

            console.print(f"Execution: {execution_id}")
            console.print(f"State: [{color}]{state}[/{color}]")

            # For interrupted state, fetch full detail for additional context
            if state == "interrupted":
                detail_resp = client.get(f"/api/executions/{execution_id}")
                if detail_resp.status_code == 200:
                    detail = detail_resp.json()
                    if detail.get("error_message"):
                        console.print(f"  Reason: {detail['error_message']}")
                    if detail.get("completed_at"):
                        console.print(f"  Interrupted at: {detail['completed_at']}")
                    if detail.get("git_sha"):
                        console.print(f"  Git SHA: {detail['git_sha']}")
    except typer.Exit:
        raise
    except Exception:
        _handle_connect_error()


@app.command()
def inject(
    execution_id: Annotated[str, typer.Argument(help="Execution ID")],
    message: Annotated[str, typer.Option("--message", "-m", help="Message to inject")],
) -> None:
    """Inject a message into a running execution."""
    try:
        with get_client() as client:
            resp = client.post(
                f"/api/executions/{execution_id}/inject",
                json={"message": message},
            )
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code == 404:
        print_error(f"Execution not found: {execution_id}")
        raise typer.Exit(1)
    if resp.status_code != 200:
        error = resp.json().get("detail", "Unknown error")
        print_error(f"Failed to inject: {error}")
        raise typer.Exit(1)

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

    try:
        with get_client() as client:
            resp = client.post(
                f"/api/executions/{execution_id}/cancel",
                json={"reason": stop_reason},
            )
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code != 200:
        error = resp.json().get("detail", "Unknown error")
        console.print(f"[red]Failed to stop: {error}[/red]")
        raise typer.Exit(1)

    data = resp.json()
    console.print(f"[orange3]Stop signal sent for execution {execution_id}[/orange3]")
    console.print(f"  State: {data.get('state', 'unknown')}")
    if data.get("message"):
        console.print(f"  Message: {data['message']}")
