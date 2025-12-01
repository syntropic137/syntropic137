"""Workflow management commands."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from aef_shared.logging import get_logger

logger = get_logger(__name__)
console = Console()

# Default workflows directory
DEFAULT_WORKFLOWS_DIR = Path("workflows/examples")

# Create workflow command group
app = typer.Typer(
    name="workflow",
    help="Manage workflows - create, list, and inspect",
    no_args_is_help=True,
)


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
    """Create a new workflow.

    Example:
        aef workflow create "My Research Workflow" --type research --repo https://github.com/org/repo
    """
    from uuid import uuid4

    from aef_adapters.storage import get_event_publisher, get_workflow_repository
    from aef_domain.contexts.workflows._shared.value_objects import (
        PhaseDefinition,
        WorkflowClassification,
        WorkflowType,
    )
    from aef_domain.contexts.workflows.create_workflow.CreateWorkflowCommand import (
        CreateWorkflowCommand,
    )
    from aef_domain.contexts.workflows.create_workflow.CreateWorkflowHandler import (
        CreateWorkflowHandler,
    )

    logger.info(
        "Creating workflow",
        name=name,
        workflow_type=workflow_type,
        description=description,
    )

    # Map string to WorkflowType enum
    type_map: dict[str, WorkflowType] = {
        "research": WorkflowType.RESEARCH,
        "planning": WorkflowType.PLANNING,
        "implementation": WorkflowType.IMPLEMENTATION,
        "review": WorkflowType.REVIEW,
        "deployment": WorkflowType.DEPLOYMENT,
        "custom": WorkflowType.CUSTOM,
    }

    wf_type = type_map.get(workflow_type.lower(), WorkflowType.CUSTOM)

    # Create a default initial phase (workflows require at least one phase)
    initial_phase = PhaseDefinition(
        phase_id=str(uuid4()),
        name="Initial Phase",
        order=1,
        description="Default initial phase - configure via YAML for production",
    )

    # Create command
    command = CreateWorkflowCommand(
        aggregate_id=str(uuid4()),
        name=name,
        description=description or f"Workflow: {name}",
        workflow_type=wf_type,
        classification=WorkflowClassification.STANDARD,
        repository_url=repo_url,
        repository_ref=repo_ref,
        phases=[initial_phase],
    )

    # Get dependencies
    repository = get_workflow_repository()
    publisher = get_event_publisher()

    # Create handler and execute
    handler = CreateWorkflowHandler(
        repository=repository,
        event_publisher=publisher,
    )

    # Run async handler
    try:
        workflow_id = asyncio.run(handler.handle(command))
        console.print(f"[bold green]✓[/bold green] Created workflow: [cyan]{name}[/cyan]")
        console.print(f"  ID: [dim]{workflow_id}[/dim]")
        console.print(f"  Type: [dim]{wf_type.value}[/dim]")

        logger.info("Workflow created successfully", workflow_id=workflow_id)

    except Exception as e:
        console.print(f"[bold red]✗[/bold red] Failed to create workflow: {e}")
        logger.error("Failed to create workflow", error=str(e))
        raise typer.Exit(1) from e


@app.command("list")
def list_workflows() -> None:
    """List all workflows in the system."""
    from aef_adapters.storage import get_event_store

    event_store = get_event_store()
    events = event_store.get_all_events()

    # Filter for WorkflowCreated events
    workflow_events = [e for e in events if e.event_type == "WorkflowCreated"]

    if not workflow_events:
        console.print("[dim]No workflows found. Create one with:[/dim]")
        console.print('  [cyan]aef workflow create "My Workflow"[/cyan]')
        return

    # Display as table
    table = Table(title="Workflows")
    table.add_column("ID", style="dim")
    table.add_column("Name", style="cyan")
    table.add_column("Type", style="green")
    table.add_column("Status", style="yellow")

    for event in workflow_events:
        data = event.event_data
        table.add_row(
            event.aggregate_id[:8] + "...",
            data.get("name", "Unknown"),
            data.get("workflow_type", "Unknown"),
            data.get("status", "created"),
        )

    console.print(table)


@app.command("show")
def show_workflow(
    workflow_id: Annotated[str, typer.Argument(help="Workflow ID (partial match supported)")],
) -> None:
    """Show details of a specific workflow."""
    from aef_adapters.storage import get_event_store

    event_store = get_event_store()
    events = event_store.get_all_events()

    # Find matching workflow
    matching = [
        e
        for e in events
        if e.event_type == "WorkflowCreated" and e.aggregate_id.startswith(workflow_id)
    ]

    if not matching:
        console.print(f"[red]No workflow found matching: {workflow_id}[/red]")
        raise typer.Exit(1)

    event = matching[0]
    data = event.event_data

    console.print("\n[bold]Workflow Details[/bold]")
    console.print(f"  [dim]ID:[/dim] {event.aggregate_id}")
    console.print(f"  [dim]Name:[/dim] [cyan]{data.get('name')}[/cyan]")
    console.print(f"  [dim]Type:[/dim] {data.get('workflow_type')}")
    console.print(f"  [dim]Status:[/dim] {data.get('status')}")
    console.print(f"  [dim]Description:[/dim] {data.get('description')}")

    phases = data.get("phases", [])
    if phases:
        console.print(f"\n  [bold]Phases ({len(phases)}):[/bold]")
        for phase in phases:
            console.print(f"    - {phase.get('name', 'Unknown')}")
    else:
        console.print("\n  [dim]No phases defined[/dim]")


@app.command("seed")
def seed_workflows(
    directory: Annotated[
        Path | None,
        typer.Option(
            "--dir",
            "-d",
            help="Directory containing workflow YAML files",
        ),
    ] = None,
    file: Annotated[
        Path | None,
        typer.Option(
            "--file",
            "-f",
            help="Single YAML file to seed",
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Validate without creating workflows",
        ),
    ] = False,
) -> None:
    """Seed workflows from YAML definitions.

    Examples:
        # Seed all workflows from default directory
        aef workflow seed

        # Seed from a specific directory
        aef workflow seed --dir workflows/custom

        # Seed a single file
        aef workflow seed --file workflows/examples/research.yaml

        # Validate without creating (dry-run)
        aef workflow seed --dry-run
    """
    from aef_adapters.storage import get_event_publisher, get_workflow_repository
    from aef_domain.contexts.workflows.create_workflow.CreateWorkflowHandler import (
        CreateWorkflowHandler,
    )
    from aef_domain.contexts.workflows.seed_workflow import WorkflowSeeder

    # Determine source
    if file and directory:
        console.print("[red]Cannot specify both --file and --dir[/red]")
        raise typer.Exit(1)

    # Get dependencies
    repository = get_workflow_repository()
    publisher = get_event_publisher()
    handler = CreateWorkflowHandler(repository=repository, event_publisher=publisher)
    seeder = WorkflowSeeder(handler)

    if dry_run:
        console.print("[yellow]DRY RUN MODE - No workflows will be created[/yellow]\n")

    if file:
        # Seed single file
        if not file.exists():
            console.print(f"[red]File not found: {file}[/red]")
            raise typer.Exit(1)

        console.print(f"Seeding from file: [cyan]{file}[/cyan]")
        result = asyncio.run(seeder.seed_from_file(file, dry_run=dry_run))

        if result.success:
            console.print(f"[green]✓[/green] {result.name} ({result.workflow_id})")
        else:
            console.print(f"[red]✗[/red] {result.name}: {result.error}")
            raise typer.Exit(1)
    else:
        # Seed from directory
        target_dir = directory or DEFAULT_WORKFLOWS_DIR
        if not target_dir.exists():
            console.print(f"[red]Directory not found: {target_dir}[/red]")
            raise typer.Exit(1)

        console.print(f"Seeding from directory: [cyan]{target_dir}[/cyan]\n")
        report = asyncio.run(seeder.seed_from_directory(target_dir, dry_run=dry_run))

        # Display results
        for result in report.results:
            if result.success:
                icon = "[green]✓[/green]"
            elif result.error and "already exists" in result.error:
                icon = "[yellow]○[/yellow]"
            else:
                icon = "[red]✗[/red]"

            msg = f"{icon} {result.name}"
            if result.error:
                msg += f" [dim]({result.error})[/dim]"
            console.print(msg)

        # Summary
        console.print()
        console.print("[bold]Summary:[/bold]")
        console.print(f"  Total:     {report.total}")
        console.print(f"  Succeeded: [green]{report.succeeded}[/green]")
        console.print(f"  Skipped:   [yellow]{report.skipped}[/yellow]")
        console.print(f"  Failed:    [red]{report.failed}[/red]")

        if report.failed > 0:
            raise typer.Exit(1)


@app.command("validate")
def validate_workflow(
    file: Annotated[
        Path,
        typer.Argument(help="YAML file to validate"),
    ],
) -> None:
    """Validate a workflow YAML file without seeding.

    Example:
        aef workflow validate workflows/examples/research.yaml
    """
    from aef_domain.contexts.workflows._shared.workflow_definition import (
        WorkflowDefinition,
        validate_workflow_yaml,
    )

    if not file.exists():
        console.print(f"[red]File not found: {file}[/red]")
        raise typer.Exit(1)

    console.print(f"Validating: [cyan]{file}[/cyan]\n")

    content = file.read_text()
    is_valid, error = validate_workflow_yaml(content)

    if is_valid:
        # Parse to show details
        definition = WorkflowDefinition.from_yaml(content)

        console.print("[green]✓ Valid workflow definition[/green]\n")
        console.print(f"  [dim]ID:[/dim] {definition.id}")
        console.print(f"  [dim]Name:[/dim] {definition.name}")
        console.print(f"  [dim]Type:[/dim] {definition.type.value}")
        console.print(f"  [dim]Classification:[/dim] {definition.classification.value}")
        console.print(f"  [dim]Phases:[/dim] {len(definition.phases)}")

        for phase in definition.phases:
            console.print(f"    {phase.order}. {phase.name}")
    else:
        console.print("[red]✗ Invalid workflow definition[/red]")
        console.print(f"  Error: {error}")
        raise typer.Exit(1)
