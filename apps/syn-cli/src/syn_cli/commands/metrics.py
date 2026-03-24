"""Metrics commands — aggregated workflow and session metrics."""

from __future__ import annotations

import typer
from rich.panel import Panel
from rich.table import Table

from syn_cli._output import console, format_cost, format_tokens
from syn_cli.commands._api_helpers import api_get, build_params

app = typer.Typer(
    name="metrics",
    help="View aggregated workflow and session metrics",
    no_args_is_help=True,
)


@app.command("show")
def show_metrics(
    workflow_id: str | None = typer.Option(None, "--workflow", "-w", help="Filter by workflow ID"),
) -> None:
    """Show aggregated metrics (optionally filtered by workflow)."""
    params = build_params(workflow_id=workflow_id)
    data = api_get("/metrics", params=params)

    panel_text = (
        f"[bold]Workflows:[/bold] {data.get('total_workflows', 0)} "
        f"(completed: {data.get('completed_workflows', 0)}, failed: {data.get('failed_workflows', 0)})\n"
        f"[bold]Sessions:[/bold] {data.get('total_sessions', 0)}\n"
        f"[bold]Tokens:[/bold] {format_tokens(data.get('total_tokens', 0))} "
        f"(in: {format_tokens(data.get('total_input_tokens', 0))}, "
        f"out: {format_tokens(data.get('total_output_tokens', 0))})\n"
        f"[bold]Cost:[/bold] {format_cost(data.get('total_cost_usd', '0'))}\n"
        f"[bold]Artifacts:[/bold] {data.get('total_artifacts', 0)}"
    )
    console.print(Panel(panel_text, title="[cyan]Metrics[/cyan]", border_style="cyan"))

    phases = data.get("phases", [])
    if phases:
        table = Table(title="Phase Metrics")
        table.add_column("Phase", style="cyan")
        table.add_column("Status")
        table.add_column("Tokens", justify="right")
        table.add_column("Cost", justify="right")
        table.add_column("Duration", justify="right")
        table.add_column("Artifacts", justify="right")

        for p in phases:
            table.add_row(
                p.get("phase_name", p.get("phase_id", "-")),
                p.get("status", "-"),
                format_tokens(p.get("total_tokens", 0)),
                format_cost(p.get("cost_usd", "0")),
                f"{p.get('duration_seconds', 0):.1f}s",
                str(p.get("artifact_count", 0)),
            )
        console.print(table)
