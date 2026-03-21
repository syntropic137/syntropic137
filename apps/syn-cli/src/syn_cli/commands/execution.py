"""Execution list and detail commands."""

from __future__ import annotations

from typing import Annotated

import typer
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

app = typer.Typer(
    name="execution",
    help="List and inspect workflow executions",
    no_args_is_help=True,
)


def _handle_connect_error() -> None:
    from syn_cli.client import get_api_url

    print_error(f"Could not connect to API at {get_api_url()}")
    console.print("[dim]Make sure the API server is running.[/dim]")
    raise typer.Exit(1)


@app.command("list")
def list_executions(
    status: Annotated[
        str | None,
        typer.Option("--status", "-s", help="Filter by status (running, completed, failed, …)"),
    ] = None,
    page: Annotated[int, typer.Option(help="Page number")] = 1,
    page_size: Annotated[int, typer.Option(help="Items per page (max 100)")] = 50,
) -> None:
    """List all workflow executions across every workflow."""
    try:
        with get_client() as client:
            params: dict[str, str | int] = {"page": page, "page_size": page_size}
            if status:
                params["status"] = status
            resp = client.get("/executions", params=params)
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code != 200:
        print_error(resp.json().get("detail", f"HTTP {resp.status_code}"))
        raise typer.Exit(1)

    data = resp.json()
    executions = data.get("executions", [])
    total = data.get("total", 0)

    if not executions:
        console.print("[dim]No executions found.[/dim]")
        return

    table = Table(title=f"Executions (page {page}, {total} total)")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Workflow")
    table.add_column("Status")
    table.add_column("Started")
    table.add_column("Phases", justify="right")
    table.add_column("Tokens", justify="right")
    table.add_column("Cost", justify="right")

    for ex in executions:
        s = ex.get("status", "")
        style = status_style(s)
        phases = f"{ex.get('completed_phases', 0)}/{ex.get('total_phases', 0)}"
        table.add_row(
            ex.get("workflow_execution_id", "")[:12],
            ex.get("workflow_name") or ex.get("workflow_id", ""),
            f"[{style}]{s}[/{style}]" if style else s,
            format_timestamp(ex.get("started_at")),
            phases,
            format_tokens(ex.get("total_tokens") or 0),
            format_cost(ex.get("total_cost_usd") or "0"),
        )

    console.print(table)
    if total > page * page_size:
        console.print(f"[dim]Showing page {page}. Use --page {page + 1} for more.[/dim]")


@app.command("show")
def show_execution(
    execution_id: Annotated[str, typer.Argument(help="Execution ID")],
) -> None:
    """Show detailed information about a single execution."""
    try:
        with get_client() as client:
            resp = client.get(f"/executions/{execution_id}")
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code == 404:
        print_error(f"Execution not found: {execution_id}")
        raise typer.Exit(1)
    if resp.status_code != 200:
        print_error(resp.json().get("detail", f"HTTP {resp.status_code}"))
        raise typer.Exit(1)

    ex = resp.json()
    s = ex.get("status", "")
    style = status_style(s)

    console.print(f"[bold]Execution:[/bold] {ex.get('workflow_execution_id', '')}")
    console.print(f"  Workflow:   {ex.get('workflow_name') or ex.get('workflow_id', '')}")
    console.print(
        f"  Status:     [{style}]{s}[/{style}]" if style else f"  Status:     {s}"
    )
    console.print(f"  Started:    {format_timestamp(ex.get('started_at'))}")
    if ex.get("completed_at"):
        console.print(f"  Completed:  {format_timestamp(ex.get('completed_at'))}")
    console.print(f"  Tokens:     {format_tokens(ex.get('total_tokens') or 0)}")
    console.print(f"  Cost:       {format_cost(ex.get('total_cost_usd') or '0')}")
    if ex.get("error_message"):
        console.print(f"  [red]Error:[/red]     {ex['error_message']}")

    phases = ex.get("phases", [])
    if phases:
        console.print()
        table = Table(title="Phases", show_edge=False)
        table.add_column("#", justify="right", style="dim")
        table.add_column("Name")
        table.add_column("Status")
        table.add_column("Started")
        table.add_column("Tokens", justify="right")
        table.add_column("Cost", justify="right")
        for i, ph in enumerate(phases, 1):
            ps = ph.get("status", "")
            pstyle = status_style(ps)
            table.add_row(
                str(i),
                ph.get("name", ""),
                f"[{pstyle}]{ps}[/{pstyle}]" if pstyle else ps,
                format_timestamp(ph.get("started_at")),
                format_tokens(ph.get("total_tokens") or 0),
                format_cost(ph.get("cost_usd") or "0"),
            )
        console.print(table)
