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
    print_error,
    status_style,
)
from syn_cli.client import get_client
from syn_cli.commands._session_models import SessionDetailResponse, SessionSummaryResponse

app = typer.Typer(
    name="sessions",
    help="View and inspect agent sessions",
    no_args_is_help=True,
)


def _handle_connect_error() -> None:
    from syn_cli.client import get_api_url

    print_error(f"Could not connect to API at {get_api_url()}")
    console.print("[dim]Make sure the API server is running.[/dim]")
    raise typer.Exit(1)


@app.command("list")
def list_sessions(
    workflow_id: str | None = typer.Option(None, "--workflow", "-w", help="Filter by workflow ID"),
    status: str | None = typer.Option(None, "--status", "-s", help="Filter by status"),
    limit: int = typer.Option(50, "--limit", "-n", help="Max results", min=1, max=200),
) -> None:
    """List agent sessions."""
    try:
        with get_client() as client:
            params: dict[str, str | int] = {"limit": limit}
            if workflow_id:
                params["workflow_id"] = workflow_id
            if status:
                params["status"] = status
            resp = client.get("/sessions", params=params)
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code != 200:
        print_error(resp.json().get("detail", f"HTTP {resp.status_code}"))
        raise typer.Exit(1)

    items = [SessionSummaryResponse(**s) for s in resp.json()]
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


@app.command("show")
def show_session(
    session_id: str = typer.Argument(..., help="Session ID"),
) -> None:
    """Show detailed information for a session."""
    try:
        with get_client() as client:
            resp = client.get(f"/sessions/{session_id}")
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code != 200:
        print_error(resp.json().get("detail", f"HTTP {resp.status_code}"))
        raise typer.Exit(1)

    s = SessionDetailResponse(**resp.json())
    style = status_style(s.status)
    status_display = f"[{style}]{s.status}[/{style}]" if style else s.status

    panel_text = (
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
        panel_text += f"\n[bold red]Error:[/bold red] {s.error_message}"

    console.print(Panel(panel_text, title="[cyan]Session Detail[/cyan]", border_style="cyan"))

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
