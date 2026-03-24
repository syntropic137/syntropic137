"""Session management commands — list and show sessions."""

from __future__ import annotations

import typer
from rich.panel import Panel
from rich.table import Table

from syn_cli._output import (
    console,
    format_cost,
    format_timestamp,
    format_tokens,
    status_style,
)
from syn_cli.commands._api_helpers import api_get, api_get_list, build_params
from syn_cli.commands._session_models import SessionDetailResponse, SessionSummaryResponse

app = typer.Typer(
    name="sessions",
    help="View and inspect agent sessions",
    no_args_is_help=True,
)


@app.command("list")
def list_sessions(
    workflow_id: str | None = typer.Option(None, "--workflow", "-w", help="Filter by workflow ID"),
    status: str | None = typer.Option(None, "--status", "-s", help="Filter by status"),
    limit: int = typer.Option(50, "--limit", "-n", help="Max results", min=1, max=200),
) -> None:
    """List agent sessions."""
    params = build_params(workflow_id=workflow_id, status=status, limit=limit)
    items = [SessionSummaryResponse(**s) for s in api_get_list("/sessions", params=params)]

    if not items:
        console.print("[dim]No sessions found.[/dim]")
        return

    table = Table(title="Sessions")
    table.add_column("ID", style="dim")
    table.add_column("Status")
    table.add_column("Provider")
    table.add_column("Tokens", justify="right")
    table.add_column("Cost", justify="right")
    table.add_column("Started", justify="right")

    for s in items:
        style = status_style(s.status)
        table.add_row(
            s.id[:12] + "..." if len(s.id) > 12 else s.id,
            f"[{style}]{s.status}[/{style}]" if style else s.status,
            s.agent_provider or "-",
            format_tokens(s.total_tokens),
            format_cost(s.total_cost_usd),
            format_timestamp(s.started_at),
        )
    console.print(table)


def _build_session_panel(s: SessionDetailResponse) -> str:
    """Build panel text for session detail view."""
    style = status_style(s.status)
    status_display = f"[{style}]{s.status}[/{style}]" if style else s.status
    text = (
        f"[bold]Session:[/bold] {s.id}\n"
        f"[bold]Status:[/bold] {status_display}\n"
        f"[bold]Provider:[/bold] {s.agent_provider or '-'} / {s.agent_model or '-'}\n"
        f"[bold]Workflow:[/bold] {s.workflow_name or s.workflow_id or '-'}\n"
        f"[bold]Tokens:[/bold] {format_tokens(s.total_tokens)} "
        f"(in: {format_tokens(s.input_tokens)}, out: {format_tokens(s.output_tokens)})\n"
        f"[bold]Cost:[/bold] {format_cost(s.total_cost_usd)}\n"
        f"[bold]Started:[/bold] {format_timestamp(s.started_at)}"
    )
    if s.error_message:
        text += f"\n[bold red]Error:[/bold red] {s.error_message}"
    return text


@app.command("show")
def show_session(
    session_id: str = typer.Argument(..., help="Session ID"),
) -> None:
    """Show detailed information for a session."""
    s = SessionDetailResponse(**api_get(f"/sessions/{session_id}"))

    console.print(
        Panel(
            _build_session_panel(s),
            title="[cyan]Session Detail[/cyan]",
            border_style="cyan",
        )
    )

    if s.operations:
        table = Table(title="Operations")
        table.add_column("Type")
        table.add_column("Tool", style="cyan")
        table.add_column("Duration", justify="right")
        table.add_column("Status")

        for op in s.operations:
            dur = f"{op.duration_seconds:.1f}s" if op.duration_seconds else "-"
            ok = "[green]ok[/green]" if op.success else "[red]fail[/red]"
            table.add_row(op.operation_type, op.tool_name or "-", dur, ok)
        console.print(table)
