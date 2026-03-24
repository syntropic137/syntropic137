"""Workflow run and status commands."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.panel import Panel
from rich.table import Table

from syn_cli._output import console, format_cost, format_tokens, print_error
from syn_cli.client import get_client
from syn_cli.commands._api_helpers import handle_connect_error
from syn_cli.commands._workflow_models import ExecutionRunResponse, parse_inputs
from syn_cli.commands._workflow_resolver import WorkflowResolver
from syn_cli.commands.workflow._crud import app


def _display_run_preview(
    workflow_name: str,
    full_id: str,
    phase_count: int,
    task: str | None,
    parsed_inputs: dict[str, object],
) -> None:
    """Display workflow execution preview panel."""
    console.print()
    console.print(
        Panel(
            f"[bold]{workflow_name}[/bold]\n"
            f"[dim]ID: {full_id}[/dim]\n"
            f"[dim]Phases: {phase_count}[/dim]",
            title="[cyan]Workflow Execution[/cyan]",
            border_style="cyan",
        )
    )
    if task:
        console.print(f"\n[bold]Task:[/bold] [green]{task}[/green]")
    if parsed_inputs:
        console.print("\n[bold]Inputs:[/bold]")
        for key, value in parsed_inputs.items():
            console.print(f"  {key}: [green]{value}[/green]")


def _execute_workflow(
    client: object,
    workflow_id: str,
    task: str | None,
    parsed_inputs: dict[str, object],
) -> None:
    """Send execute request and display result."""
    body: dict[str, object] = {"inputs": {k: str(v) for k, v in parsed_inputs.items()}}
    if task:
        body["task"] = task

    with console.status("Executing workflow..."):
        exec_resp = client.post(  # type: ignore[union-attr]
            f"/workflows/{workflow_id}/execute",
            json=body,
            timeout=300.0,
        )

    if exec_resp.status_code != 200:
        print_error(exec_resp.json().get("detail", f"HTTP {exec_resp.status_code}"))
        raise typer.Exit(1)

    result = ExecutionRunResponse(**exec_resp.json())
    if result.status == "started":
        console.print("\n[bold green]Workflow execution started[/bold green]")
        console.print(f"  Execution ID: {result.execution_id}")
    else:
        console.print(f"\n[yellow]Status: {result.status}[/yellow]")


@app.command("run")
def run_workflow(
    workflow_id: Annotated[
        str,
        typer.Argument(help="Workflow ID (partial match supported)"),
    ],
    inputs: Annotated[
        list[str] | None,
        typer.Option("--input", "-i", help="Input variables as key=value"),
    ] = None,
    task: Annotated[
        str | None,
        typer.Option("--task", "-t", help="Primary task description ($ARGUMENTS)"),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", "-n", help="Validate without executing"),
    ] = False,
    quiet: Annotated[
        bool,
        typer.Option("--quiet", "-q", help="Minimal output"),
    ] = False,
    container: Annotated[  # noqa: ARG001
        bool,
        typer.Option("--container/--no-container", "-c", help="Run in isolated container"),
    ] = True,
    tenant_id: Annotated[  # noqa: ARG001
        str | None,
        typer.Option("--tenant", help="Tenant ID for multi-tenant attribution"),
    ] = None,
) -> None:
    """Execute a workflow."""
    parsed_inputs = parse_inputs(inputs)

    try:
        with get_client() as client:
            wf = WorkflowResolver(client).resolve(workflow_id)

            if not quiet:
                _display_run_preview(wf.name, wf.id, wf.phase_count, task, parsed_inputs)

            if dry_run:
                console.print("\n[yellow]DRY RUN[/yellow] - Workflow is valid and ready to execute")
                console.print("[dim]Remove --dry-run to execute[/dim]")
                return

            _execute_workflow(client, wf.id, task, parsed_inputs)
    except typer.Exit:
        raise
    except Exception:
        handle_connect_error()


def _render_runs_table(runs: list[dict[str, object]], workflow_id: str) -> None:
    """Render execution runs table or empty-state message."""
    if not runs:
        console.print("\n[dim]No executions found.[/dim]")
        console.print(f"[dim]Run with: syn workflow run {workflow_id}[/dim]")
        return

    table = Table(title="Executions")
    table.add_column("ID", style="dim")
    table.add_column("Status")
    table.add_column("Phases", justify="right")
    table.add_column("Tokens", justify="right")
    table.add_column("Cost", justify="right")

    for run in runs:
        table.add_row(
            str(run.get("workflow_execution_id", ""))[:12] + "...",
            str(run.get("status", "")),
            f"{run.get('completed_phases', 0)}/{run.get('total_phases', 0)}",
            format_tokens(int(str(run.get("total_tokens", 0) or 0))),
            format_cost(str(run.get("total_cost_usd", "0"))),
        )
    console.print(table)


@app.command("status")
def workflow_status(
    workflow_id: Annotated[
        str,
        typer.Argument(help="Workflow ID (partial match supported)"),
    ],
) -> None:
    """Show execution history for a workflow."""
    try:
        with get_client() as client:
            wf = WorkflowResolver(client).resolve(workflow_id)

            console.print(
                Panel(
                    f"[bold]{wf.name}[/bold]\n[dim]ID: {wf.id}[/dim]",
                    title="[cyan]Workflow Status[/cyan]",
                    border_style="cyan",
                )
            )

            exec_resp = client.get(f"/workflows/{wf.id}/runs")
    except typer.Exit:
        raise
    except Exception:
        handle_connect_error()

    if exec_resp.status_code != 200:
        print_error(exec_resp.json().get("detail", f"HTTP {exec_resp.status_code}"))
        raise typer.Exit(1)

    _render_runs_table(exec_resp.json().get("runs", []), workflow_id)
