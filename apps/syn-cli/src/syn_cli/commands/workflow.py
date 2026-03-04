"""Workflow management commands — create, list, show, run, status, validate."""

from __future__ import annotations

import re
from pathlib import Path  # noqa: TC003 — Typer needs Path at runtime
from typing import Annotated, Any

import typer
from rich.panel import Panel
from rich.table import Table

from syn_cli._output import console, format_cost, format_tokens, print_error
from syn_cli.client import get_client

app = typer.Typer(
    name="workflow",
    help="Manage workflows - create, list, run, and inspect",
    no_args_is_help=True,
)


def _parse_inputs(inputs: list[str] | None) -> dict[str, Any]:
    """Parse key=value input pairs into a dictionary."""
    if not inputs:
        return {}

    result: dict[str, Any] = {}
    for item in inputs:
        if "=" not in item:
            console.print(
                f"[yellow]Warning: Ignoring invalid input '{item}' (expected key=value)[/yellow]"
            )
            continue

        key, value = item.split("=", 1)
        key = key.strip()

        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            result[key] = value[1:-1]
        elif value.lower() == "true":
            result[key] = True
        elif value.lower() == "false":
            result[key] = False
        elif re.match(r"^-?\d+$", value):
            result[key] = int(value)
        elif re.match(r"^-?\d+\.\d+$", value):
            result[key] = float(value)
        else:
            result[key] = value

    return result


def _handle_connect_error() -> None:
    from syn_cli.client import get_api_url

    print_error(f"Could not connect to API at {get_api_url()}")
    console.print(
        "[dim]Make sure the API server is running (syn-api or uvicorn syn_api.main:app).[/dim]"
    )
    raise typer.Exit(1)


@app.command("create")
def create_workflow(
    name: Annotated[str, typer.Argument(help="Name of the workflow")],
    workflow_type: Annotated[
        str,
        typer.Option(
            "--type",
            "-t",
            help="Type: research, planning, implementation, review, deployment, custom",
        ),
    ] = "custom",
    repo_url: Annotated[
        str,
        typer.Option("--repo", "-r", help="Repository URL for the workflow"),
    ] = "https://github.com/example/repo",
    repo_ref: Annotated[
        str,
        typer.Option("--ref", help="Repository ref/branch"),
    ] = "main",
    description: Annotated[
        str | None,
        typer.Option("--description", "-d", help="Workflow description"),
    ] = None,
) -> None:
    """Create a new workflow."""
    try:
        with get_client() as client:
            resp = client.post(
                "/workflows",
                json={
                    "name": name,
                    "workflow_type": workflow_type,
                    "repository_url": repo_url,
                    "repository_ref": repo_ref,
                    "description": description,
                },
            )
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code != 200:
        print_error(resp.json().get("detail", f"HTTP {resp.status_code}"))
        raise typer.Exit(1)

    data = resp.json()
    workflow_id = data.get("id") or data.get("workflow_id", "unknown")
    console.print(f"[bold green]Created workflow:[/bold green] [cyan]{name}[/cyan]")
    console.print(f"  ID: [dim]{workflow_id}[/dim]")
    console.print(f"  Type: [dim]{workflow_type}[/dim]")


@app.command("list")
def list_workflows() -> None:
    """List all workflows in the system."""
    try:
        with get_client() as client:
            resp = client.get("/workflows")
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code != 200:
        print_error(resp.json().get("detail", f"HTTP {resp.status_code}"))
        raise typer.Exit(1)

    data = resp.json()
    workflows = data.get("workflows", [])

    if not workflows:
        console.print("[dim]No workflows found. Create one with:[/dim]")
        console.print('  [cyan]syn workflow create "My Workflow"[/cyan]')
        return

    table = Table(title="Workflows")
    table.add_column("ID", style="dim")
    table.add_column("Name", style="cyan")
    table.add_column("Type", style="green")
    table.add_column("Phases", justify="right")

    for w in workflows:
        table.add_row(
            w["id"][:12] + "...",
            w["name"],
            w["workflow_type"],
            str(w.get("phase_count", 0)),
        )
    console.print(table)


@app.command("show")
def show_workflow(
    workflow_id: Annotated[str, typer.Argument(help="Workflow ID (partial match supported)")],
) -> None:
    """Show details of a specific workflow."""
    try:
        with get_client() as client:
            # Get all workflows for partial ID matching
            list_resp = client.get("/workflows")
            if list_resp.status_code != 200:
                print_error("Failed to list workflows")
                raise typer.Exit(1)

            workflows = list_resp.json().get("workflows", [])
            matching = [w for w in workflows if w["id"].startswith(workflow_id)]

            if not matching:
                print_error(f"No workflow found matching: {workflow_id}")
                raise typer.Exit(1)

            if len(matching) > 1:
                console.print(f"[yellow]Multiple workflows match '{workflow_id}':[/yellow]")
                for w in matching[:5]:
                    console.print(f"  {w['id'][:12]}... - {w['name']}")
                console.print("[dim]Please provide a more specific ID[/dim]")
                raise typer.Exit(1)

            full_id = matching[0]["id"]
            resp = client.get(f"/workflows/{full_id}")
    except typer.Exit:
        raise
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code != 200:
        print_error(f"Workflow not found: {resp.json().get('detail', '')}")
        raise typer.Exit(1)

    detail = resp.json()
    console.print("\n[bold]Workflow Details[/bold]")
    console.print(f"  [dim]ID:[/dim] {detail['id']}")
    console.print(f"  [dim]Name:[/dim] [cyan]{detail['name']}[/cyan]")
    console.print(f"  [dim]Type:[/dim] {detail['workflow_type']}")
    console.print(f"  [dim]Classification:[/dim] {detail.get('classification', '')}")
    phases = detail.get("phases", [])
    if phases:
        console.print(f"\n  [bold]Phases ({len(phases)}):[/bold]")
        for phase in phases:
            console.print(f"    - {phase.get('name', 'unnamed')}")
    else:
        console.print("\n  [dim]No phases defined[/dim]")


@app.command("validate")
def validate_workflow(
    file: Annotated[Path, typer.Argument(help="YAML file to validate")],
) -> None:
    """Validate a workflow YAML file without creating it."""
    try:
        with get_client() as client:
            resp = client.post("/workflows/validate", json={"file": str(file)})
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code != 200:
        print_error(resp.json().get("detail", f"HTTP {resp.status_code}"))
        raise typer.Exit(1)

    validation = resp.json()
    if validation.get("valid"):
        console.print("[green]Valid workflow definition[/green]\n")
        console.print(f"  [dim]Name:[/dim] {validation.get('name', '')}")
        console.print(f"  [dim]Type:[/dim] {validation.get('workflow_type', '')}")
        console.print(f"  [dim]Phases:[/dim] {validation.get('phase_count', 0)}")
    else:
        console.print("[red]Invalid workflow definition[/red]")
        for error in validation.get("errors", []):
            console.print(f"  {error}")
        raise typer.Exit(1)


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
    parsed_inputs = _parse_inputs(inputs)

    try:
        with get_client() as client:
            # Resolve partial ID
            list_resp = client.get("/workflows")
            if list_resp.status_code != 200:
                print_error("Failed to list workflows")
                raise typer.Exit(1)

            workflows = list_resp.json().get("workflows", [])
            matching = [w for w in workflows if w["id"].startswith(workflow_id)]

            if not matching:
                print_error(f"No workflow found matching: {workflow_id}")
                console.print("[dim]Use 'syn workflow list' to see available workflows[/dim]")
                raise typer.Exit(1)

            if len(matching) > 1:
                console.print(f"[yellow]Multiple workflows match '{workflow_id}':[/yellow]")
                for w in matching[:5]:
                    console.print(f"  {w['id'][:12]}... - {w['name']}")
                console.print("[dim]Please provide a more specific ID[/dim]")
                raise typer.Exit(1)

            full_workflow_id = matching[0]["id"]
            workflow_name = matching[0]["name"]
            phase_count = matching[0].get("phase_count", 0)

            if not quiet:
                console.print()
                console.print(
                    Panel(
                        f"[bold]{workflow_name}[/bold]\n"
                        f"[dim]ID: {full_workflow_id}[/dim]\n"
                        f"[dim]Phases: {phase_count}[/dim]",
                        title="[cyan]Workflow Execution[/cyan]",
                        border_style="cyan",
                    )
                )
                if parsed_inputs:
                    console.print("\n[bold]Inputs:[/bold]")
                    for key, value in parsed_inputs.items():
                        console.print(f"  {key}: [green]{value}[/green]")

            if dry_run:
                console.print("\n[yellow]DRY RUN[/yellow] - Workflow is valid and ready to execute")
                console.print("[dim]Remove --dry-run to execute[/dim]")
                return

            # Execute
            with console.status("Executing workflow..."):
                exec_resp = client.post(
                    f"/workflows/{full_workflow_id}/execute",
                    json={"inputs": {k: str(v) for k, v in parsed_inputs.items()}},
                    timeout=300.0,
                )

    except typer.Exit:
        raise
    except Exception:
        _handle_connect_error()
        return

    if exec_resp.status_code != 200:
        print_error(exec_resp.json().get("detail", f"HTTP {exec_resp.status_code}"))
        raise typer.Exit(1)

    result = exec_resp.json()
    status = result.get("status", "unknown")
    if status == "started":
        console.print("\n[bold green]Workflow execution started[/bold green]")
        console.print(f"  Execution ID: {result.get('execution_id', 'unknown')}")
    else:
        console.print(f"\n[yellow]Status: {status}[/yellow]")


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
            # Resolve partial ID
            list_resp = client.get("/workflows")
            if list_resp.status_code != 200:
                print_error("Failed to list workflows")
                raise typer.Exit(1)

            workflows = list_resp.json().get("workflows", [])
            matching = [w for w in workflows if w["id"].startswith(workflow_id)]

            if not matching:
                print_error(f"No workflow found matching: {workflow_id}")
                raise typer.Exit(1)

            full_id = matching[0]["id"]
            workflow_name = matching[0]["name"]

            console.print(
                Panel(
                    f"[bold]{workflow_name}[/bold]\n[dim]ID: {full_id}[/dim]",
                    title="[cyan]Workflow Status[/cyan]",
                    border_style="cyan",
                )
            )

            exec_resp = client.get(f"/workflows/{full_id}/runs")
    except typer.Exit:
        raise
    except Exception:
        _handle_connect_error()
        return

    if exec_resp.status_code != 200:
        print_error(exec_resp.json().get("detail", f"HTTP {exec_resp.status_code}"))
        raise typer.Exit(1)

    data = exec_resp.json()
    runs = data.get("runs", [])

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
            run["workflow_execution_id"][:12] + "...",
            run["status"],
            f"{run.get('completed_phases', 0)}/{run.get('total_phases', 0)}",
            format_tokens(run.get("total_tokens", 0)),
            format_cost(run.get("total_cost_usd", "0")),
        )
    console.print(table)
