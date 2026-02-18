"""Workflow management commands — create, list, show, run, status, validate."""

from __future__ import annotations

import re
from pathlib import Path  # noqa: TC003 — Typer needs Path at runtime
from typing import Annotated, Any

import typer
from rich.panel import Panel
from rich.table import Table

from syn_api.types import Err, Ok
from syn_cli._async import run
from syn_cli._output import console, format_cost, format_tokens

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
    import syn_api.v1.workflows as wf

    result = run(
        wf.create_workflow(
            name=name,
            workflow_type=workflow_type,
            repository_url=repo_url,
            repository_ref=repo_ref,
            description=description,
        )
    )

    match result:
        case Ok(workflow_id):
            console.print(f"[bold green]Created workflow:[/bold green] [cyan]{name}[/cyan]")
            console.print(f"  ID: [dim]{workflow_id}[/dim]")
            console.print(f"  Type: [dim]{workflow_type}[/dim]")
        case Err(error, message=msg):
            console.print(f"[bold red]Failed to create workflow:[/bold red] {msg or error}")
            raise typer.Exit(1)


@app.command("list")
def list_workflows() -> None:
    """List all workflows in the system."""
    import syn_api.v1.workflows as wf

    result = run(wf.list_workflows())

    match result:
        case Ok(workflows):
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
                    w.id[:12] + "...",
                    w.name,
                    w.workflow_type,
                    str(w.phase_count),
                )
            console.print(table)
        case Err(error, message=msg):
            console.print(f"[red]Failed to list workflows: {msg or error}[/red]")
            raise typer.Exit(1)


@app.command("show")
def show_workflow(
    workflow_id: Annotated[str, typer.Argument(help="Workflow ID (partial match supported)")],
) -> None:
    """Show details of a specific workflow."""
    import syn_api.v1.workflows as wf

    # Support partial ID matching via list + filter
    list_result = run(wf.list_workflows())
    if isinstance(list_result, Err):
        console.print(f"[red]Failed to list workflows: {list_result.message}[/red]")
        raise typer.Exit(1)

    matching = [w for w in list_result.value if w.id.startswith(workflow_id)]

    if not matching:
        console.print(f"[red]No workflow found matching: {workflow_id}[/red]")
        raise typer.Exit(1)

    if len(matching) > 1:
        console.print(f"[yellow]Multiple workflows match '{workflow_id}':[/yellow]")
        for w in matching[:5]:
            console.print(f"  {w.id[:12]}... - {w.name}")
        console.print("[dim]Please provide a more specific ID[/dim]")
        raise typer.Exit(1)

    full_id = matching[0].id
    detail_result = run(wf.get_workflow(full_id))

    match detail_result:
        case Ok(detail):
            console.print("\n[bold]Workflow Details[/bold]")
            console.print(f"  [dim]ID:[/dim] {detail.id}")
            console.print(f"  [dim]Name:[/dim] [cyan]{detail.name}[/cyan]")
            console.print(f"  [dim]Type:[/dim] {detail.workflow_type}")
            console.print(f"  [dim]Classification:[/dim] {detail.classification}")
            if detail.phases:
                console.print(f"\n  [bold]Phases ({len(detail.phases)}):[/bold]")
                for phase in detail.phases:
                    console.print(f"    - {phase.name}")
            else:
                console.print("\n  [dim]No phases defined[/dim]")
        case Err(error, message=msg):
            console.print(f"[red]Workflow not found: {msg or error}[/red]")
            raise typer.Exit(1)


@app.command("validate")
def validate_workflow(
    file: Annotated[Path, typer.Argument(help="YAML file to validate")],
) -> None:
    """Validate a workflow YAML file without creating it."""
    import syn_api.v1.workflows as wf

    result = run(wf.validate_yaml(str(file)))

    match result:
        case Ok(validation):
            if validation.valid:
                console.print("[green]Valid workflow definition[/green]\n")
                console.print(f"  [dim]Name:[/dim] {validation.name}")
                console.print(f"  [dim]Type:[/dim] {validation.workflow_type}")
                console.print(f"  [dim]Phases:[/dim] {validation.phase_count}")
            else:
                console.print("[red]Invalid workflow definition[/red]")
                for error in validation.errors:
                    console.print(f"  {error}")
                raise typer.Exit(1)
        case Err(error, message=msg):
            console.print(f"[red]{msg or error}[/red]")
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
    container: Annotated[
        bool,
        typer.Option("--container/--no-container", "-c", help="Run in isolated container"),
    ] = True,
    tenant_id: Annotated[
        str | None,
        typer.Option("--tenant", help="Tenant ID for multi-tenant attribution"),
    ] = None,
) -> None:
    """Execute a workflow."""
    import syn_api.v1.executions as ex
    import syn_api.v1.workflows as wf

    parsed_inputs = _parse_inputs(inputs)

    # Resolve partial ID
    list_result = run(wf.list_workflows())
    if isinstance(list_result, Err):
        console.print(f"[red]Failed to list workflows: {list_result.message}[/red]")
        raise typer.Exit(1)

    matching = [w for w in list_result.value if w.id.startswith(workflow_id)]

    if not matching:
        console.print(f"[red]No workflow found matching: {workflow_id}[/red]")
        console.print("[dim]Use 'syn workflow list' to see available workflows[/dim]")
        raise typer.Exit(1)

    if len(matching) > 1:
        console.print(f"[yellow]Multiple workflows match '{workflow_id}':[/yellow]")
        for w in matching[:5]:
            console.print(f"  {w.id[:12]}... - {w.name}")
        console.print("[dim]Please provide a more specific ID[/dim]")
        raise typer.Exit(1)

    full_workflow_id = matching[0].id
    workflow_name = matching[0].name
    phase_count = matching[0].phase_count

    # Show workflow info
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
        exec_result = run(
            ex.execute(
                workflow_id=full_workflow_id,
                inputs={k: str(v) for k, v in parsed_inputs.items()},
                use_container=container,
                tenant_id=tenant_id,
            )
        )

    match exec_result:
        case Ok(summary):
            if summary.status == "completed":
                console.print("\n[bold green]Workflow completed successfully[/bold green]")
            elif summary.status == "failed":
                console.print("\n[bold red]Workflow failed[/bold red]")
                if summary.error_message:
                    console.print(f"[red]Error: {summary.error_message}[/red]")
            else:
                console.print(f"\n[yellow]Workflow status: {summary.status}[/yellow]")

            if not quiet:
                console.print()
                console.print("[bold]Summary:[/bold]")
                console.print(
                    f"  Phases:  {summary.completed_phases}/{summary.total_phases} completed"
                )
                console.print(f"  Tokens:  {format_tokens(summary.total_tokens)}")
                console.print(f"  Cost:    {format_cost(summary.total_cost_usd)}")

            if summary.status == "failed":
                raise typer.Exit(1)
        case Err(error, message=msg):
            console.print(f"\n[bold red]Execution failed:[/bold red] {msg or error}")
            raise typer.Exit(1)


@app.command("status")
def workflow_status(
    workflow_id: Annotated[
        str,
        typer.Argument(help="Workflow ID (partial match supported)"),
    ],
) -> None:
    """Show execution history for a workflow."""
    import syn_api.v1.executions as ex
    import syn_api.v1.workflows as wf

    # Resolve partial ID and show executions
    list_result = run(wf.list_workflows())
    if isinstance(list_result, Err):
        console.print(f"[red]Failed: {list_result.message}[/red]")
        raise typer.Exit(1)

    matching = [w for w in list_result.value if w.id.startswith(workflow_id)]
    if not matching:
        console.print(f"[red]No workflow found matching: {workflow_id}[/red]")
        raise typer.Exit(1)

    full_id = matching[0].id
    workflow_name = matching[0].name

    console.print(
        Panel(
            f"[bold]{workflow_name}[/bold]\n[dim]ID: {full_id}[/dim]",
            title="[cyan]Workflow Status[/cyan]",
            border_style="cyan",
        )
    )

    exec_result = run(ex.list_(workflow_id=full_id))
    match exec_result:
        case Ok(executions):
            if not executions:
                console.print("\n[dim]No executions found.[/dim]")
                console.print(f"[dim]Run with: syn workflow run {workflow_id}[/dim]")
                return

            table = Table(title="Executions")
            table.add_column("ID", style="dim")
            table.add_column("Status")
            table.add_column("Phases", justify="right")
            table.add_column("Tokens", justify="right")
            table.add_column("Cost", justify="right")

            for execution in executions:
                table.add_row(
                    execution.workflow_execution_id[:12] + "...",
                    execution.status,
                    f"{execution.completed_phases}/{execution.total_phases}",
                    format_tokens(execution.total_tokens),
                    format_cost(execution.total_cost_usd),
                )
            console.print(table)
        case Err(error, message=msg):
            console.print(f"[red]Failed: {msg or error}[/red]")
            raise typer.Exit(1)
