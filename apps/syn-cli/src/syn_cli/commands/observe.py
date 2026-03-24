"""Observability commands — tool timelines and token breakdowns."""

from __future__ import annotations

import typer
from rich.panel import Panel
from rich.table import Table

from syn_cli._output import console, format_cost, format_duration, format_tokens
from syn_cli.commands._api_helpers import api_get

app = typer.Typer(
    name="observe",
    help="Observability data for sessions — tool timelines and token metrics",
    no_args_is_help=True,
)


@app.command("tools")
def tool_timeline(
    session_id: str = typer.Argument(..., help="Session ID"),
    limit: int = typer.Option(100, "--limit", "-n", help="Max results", min=1, max=500),
) -> None:
    """Show tool execution timeline for a session."""
    data = api_get(
        f"/observability/sessions/{session_id}/tools",
        params={"limit": limit},
    )

    executions = data.get("executions", [])
    if not executions:
        console.print("[dim]No tool executions found for this session.[/dim]")
        return

    console.print(
        f"[dim]Session: {data.get('session_id', session_id)}  |  Total: {data.get('total_executions', len(executions))}[/dim]"
    )

    table = Table(title="Tool Timeline")
    table.add_column("Tool", style="cyan")
    table.add_column("Type")
    table.add_column("Duration", justify="right")
    table.add_column("Status")

    for ex in executions:
        dur = format_duration(ex.get("duration_ms", 0)) if ex.get("duration_ms") else "-"
        ok = "[green]ok[/green]" if ex.get("success", True) else "[red]fail[/red]"
        table.add_row(
            ex.get("tool_name", "-"),
            ex.get("operation_type", "-"),
            dur,
            ok,
        )
    console.print(table)


@app.command("tokens")
def token_metrics(
    session_id: str = typer.Argument(..., help="Session ID"),
) -> None:
    """Show token breakdown for a session."""
    data = api_get(f"/observability/sessions/{session_id}/tokens")

    panel_text = (
        f"[bold]Session:[/bold] {data.get('session_id', session_id)}\n"
        f"[bold]Input Tokens:[/bold] {format_tokens(data.get('input_tokens', 0))}\n"
        f"[bold]Output Tokens:[/bold] {format_tokens(data.get('output_tokens', 0))}\n"
        f"[bold]Total Tokens:[/bold] {format_tokens(data.get('total_tokens', 0))}\n"
        f"[bold]Cache Creation:[/bold] {format_tokens(data.get('cache_creation_tokens', 0))}\n"
        f"[bold]Cache Read:[/bold] {format_tokens(data.get('cache_read_tokens', 0))}\n"
        f"[bold]Cost:[/bold] {format_cost(data.get('total_cost_usd', '0'))}"
    )
    console.print(Panel(panel_text, title="[cyan]Token Metrics[/cyan]", border_style="cyan"))
