"""Workflow management commands."""

from __future__ import annotations

import asyncio
import re
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from aef_shared.logging import get_logger

logger = get_logger(__name__)
console = Console()

# Default workflows directory
DEFAULT_WORKFLOWS_DIR = Path("workflows/examples")

# Create workflow command group
app = typer.Typer(
    name="workflow",
    help="Manage workflows - create, list, run, and inspect",
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
    from aef_adapters.storage import (
        connect_event_store,
        disconnect_event_store,
        get_event_publisher,
        get_workflow_repository,
    )
    from aef_domain.contexts.workflows.create_workflow.CreateWorkflowHandler import (
        CreateWorkflowHandler,
    )
    from aef_domain.contexts.workflows.seed_workflow import WorkflowSeeder

    # Determine source
    if file and directory:
        console.print("[red]Cannot specify both --file and --dir[/red]")
        raise typer.Exit(1)

    # Result container for async function
    result_container: dict[str, Any] = {}

    async def _seed_workflows() -> None:
        """Async wrapper for seeding workflows with proper connection management."""
        # Connect to event store
        await connect_event_store()

        try:
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
                    result_container["exit_code"] = 1
                    return

                console.print(f"Seeding from file: [cyan]{file}[/cyan]")
                result = await seeder.seed_from_file(file, dry_run=dry_run)

                if result.success:
                    console.print(f"[green]✓[/green] {result.name} ({result.workflow_id})")
                    result_container["exit_code"] = 0
                else:
                    console.print(f"[red]✗[/red] {result.name}: {result.error}")
                    result_container["exit_code"] = 1
            else:
                # Seed from directory
                target_dir = directory or DEFAULT_WORKFLOWS_DIR
                if not target_dir.exists():
                    console.print(f"[red]Directory not found: {target_dir}[/red]")
                    result_container["exit_code"] = 1
                    return

                console.print(f"Seeding from directory: [cyan]{target_dir}[/cyan]\n")
                report = await seeder.seed_from_directory(target_dir, dry_run=dry_run)
                result_container["report"] = report
        finally:
            # Disconnect from event store
            await disconnect_event_store()

    asyncio.run(_seed_workflows())

    # Handle single file result
    if file:
        if result_container.get("exit_code", 0) != 0:
            raise typer.Exit(1)
        return

    # Handle directory results
    report = result_container.get("report")
    if report is None:
        raise typer.Exit(1)

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


def _parse_inputs(inputs: list[str] | None) -> dict[str, Any]:
    """Parse key=value input pairs into a dictionary.

    Supports:
        - key=value (string)
        - key=123 (integer)
        - key=1.5 (float)
        - key=true/false (boolean)
        - key="quoted value" (string with spaces)

    Args:
        inputs: List of key=value strings.

    Returns:
        Dictionary of parsed inputs.
    """
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

        # Handle quoted strings
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            result[key] = value[1:-1]
        # Handle booleans
        elif value.lower() == "true":
            result[key] = True
        elif value.lower() == "false":
            result[key] = False
        # Handle integers
        elif re.match(r"^-?\d+$", value):
            result[key] = int(value)
        # Handle floats
        elif re.match(r"^-?\d+\.\d+$", value):
            result[key] = float(value)
        else:
            result[key] = value

    return result


def _format_cost(cost: Decimal) -> str:
    """Format cost for display."""
    if cost < Decimal("0.01"):
        return f"${cost:.4f}"
    return f"${cost:.2f}"


def _format_tokens(tokens: int) -> str:
    """Format token count for display."""
    if tokens >= 1_000_000:
        return f"{tokens / 1_000_000:.1f}M"
    if tokens >= 1_000:
        return f"{tokens / 1_000:.1f}K"
    return str(tokens)


@app.command("run")
def run_workflow(
    workflow_id: Annotated[
        str,
        typer.Argument(help="Workflow ID (partial match supported)"),
    ],
    inputs: Annotated[
        list[str] | None,
        typer.Option(
            "--input",
            "-i",
            help="Input variables as key=value (can be repeated)",
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            "-n",
            help="Validate and show execution plan without running",
        ),
    ] = False,
    quiet: Annotated[
        bool,
        typer.Option(
            "--quiet",
            "-q",
            help="Minimal output, only show final result",
        ),
    ] = False,
) -> None:
    """Execute a workflow.

    Examples:
        # Run workflow with inputs
        aef workflow run research-workflow --input topic="AI agents" --input depth=3

        # Dry run to validate
        aef workflow run research-workflow --dry-run

        # Run quietly (minimal output)
        aef workflow run research-workflow --quiet
    """
    from aef_adapters.agents import (
        InstrumentedAgent,
        MockAgent,
        MockAgentConfig,
    )
    from aef_adapters.hooks import ValidatorRegistry, get_hook_client
    from aef_adapters.storage import (
        get_artifact_repository,
        get_event_publisher,
        get_event_store,
        get_session_repository,
        get_workflow_repository,
    )
    from aef_domain.contexts.workflows._shared.execution_value_objects import (
        ExecutionStatus,
        PhaseStatus,
    )
    from aef_domain.contexts.workflows.execute_workflow.WorkflowExecutionEngine import (
        WorkflowExecutionEngine,
        WorkflowNotFoundError,
    )

    # Parse inputs
    parsed_inputs = _parse_inputs(inputs)

    logger.info(
        "Running workflow",
        workflow_id=workflow_id,
        inputs=parsed_inputs,
        dry_run=dry_run,
    )

    # Find workflow by ID prefix
    event_store = get_event_store()

    events = event_store.get_all_events()
    matching = [
        e
        for e in events
        if e.event_type == "WorkflowCreated" and e.aggregate_id.startswith(workflow_id)
    ]

    if not matching:
        console.print(f"[red]No workflow found matching: {workflow_id}[/red]")
        console.print("[dim]Use 'aef workflow list' to see available workflows[/dim]")
        raise typer.Exit(1)

    if len(matching) > 1:
        console.print(f"[yellow]Multiple workflows match '{workflow_id}':[/yellow]")
        for e in matching[:5]:
            console.print(f"  • {e.aggregate_id[:8]}... - {e.event_data.get('name')}")
        console.print("[dim]Please provide a more specific ID[/dim]")
        raise typer.Exit(1)

    full_workflow_id = matching[0].aggregate_id
    workflow_data = matching[0].event_data
    workflow_name = workflow_data.get("name", "Unknown")
    phases = workflow_data.get("phases", [])

    # Show workflow info
    console.print()
    console.print(
        Panel(
            f"[bold]{workflow_name}[/bold]\n"
            f"[dim]ID: {full_workflow_id}[/dim]\n"
            f"[dim]Phases: {len(phases)}[/dim]",
            title="[cyan]Workflow Execution[/cyan]",
            border_style="cyan",
        )
    )

    if parsed_inputs:
        console.print("\n[bold]Inputs:[/bold]")
        for key, value in parsed_inputs.items():
            console.print(f"  • {key}: [green]{value}[/green]")

    if dry_run:
        console.print("\n[yellow]DRY RUN MODE[/yellow] - Validating execution plan\n")

        # Show phases that would execute
        console.print("[bold]Execution Plan:[/bold]")
        for i, phase in enumerate(phases, 1):
            phase_name = phase.get("name", f"Phase {i}")
            console.print(f"  {i}. {phase_name}")
            if phase.get("description"):
                console.print(f"     [dim]{phase.get('description')}[/dim]")

        console.print()
        console.print("[green]✓[/green] Workflow is valid and ready to execute")
        console.print("[dim]Remove --dry-run to execute[/dim]")
        return

    # Execute the workflow
    console.print()

    async def _execute() -> None:
        """Execute workflow asynchronously."""
        # Get repositories
        workflow_repo = get_workflow_repository()
        session_repo = get_session_repository()
        artifact_repo = get_artifact_repository()
        publisher = get_event_publisher()

        # Create agent factory - use mock agent for now
        # In production, this would use get_agent() to get real agents
        def agent_factory(provider: str) -> InstrumentedAgent:
            """Create an instrumented agent for the given provider."""
            # For now, use mock agent. In production:
            # base_agent = get_agent(AgentProvider(provider))
            mock_config = MockAgentConfig(
                default_response=f"Mock response for {provider} agent execution. "
                "This is a placeholder - configure real agents for production use."
            )
            base_agent = MockAgent(mock_config)
            hook_client = get_hook_client()
            validators = ValidatorRegistry()
            return InstrumentedAgent(
                agent=base_agent,
                hook_client=hook_client,
                validators=validators,
            )

        # Create engine
        engine = WorkflowExecutionEngine(
            workflow_repository=workflow_repo,
            session_repository=session_repo,
            artifact_repository=artifact_repo,
            agent_factory=agent_factory,
            event_publisher=publisher,
        )

        # Setup progress display
        if not quiet:
            progress = Progress(
                SpinnerColumn(),
                TextColumn("[bold blue]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                TimeElapsedColumn(),
                console=console,
            )

            with progress:
                # Create overall task
                overall_task = progress.add_task(
                    f"Executing {workflow_name}",
                    total=len(phases),
                )

                # Execute and track progress
                try:
                    result = await engine.execute(
                        workflow_id=full_workflow_id,
                        inputs=parsed_inputs,
                    )

                    # Update progress for completed phases
                    for _phase_result in result.phase_results:
                        progress.update(overall_task, advance=1)

                except WorkflowNotFoundError:
                    console.print(f"[red]Workflow not found: {full_workflow_id}[/red]")
                    raise typer.Exit(1)  # noqa: B904 - intentional exit

        else:
            # Quiet mode - just execute
            try:
                result = await engine.execute(
                    workflow_id=full_workflow_id,
                    inputs=parsed_inputs,
                )
            except WorkflowNotFoundError:
                console.print(f"[red]Workflow not found: {full_workflow_id}[/red]")
                raise typer.Exit(1)  # noqa: B904 - intentional exit

        # Display results
        console.print()

        if result.status == ExecutionStatus.COMPLETED:
            console.print("[bold green]✓ Workflow completed successfully[/bold green]\n")
        elif result.status == ExecutionStatus.FAILED:
            console.print("[bold red]✗ Workflow failed[/bold red]\n")
            if result.error_message:
                console.print(f"[red]Error: {result.error_message}[/red]\n")
        else:
            console.print(f"[yellow]Workflow status: {result.status.value}[/yellow]\n")

        # Phase results table
        if not quiet:
            table = Table(title="Phase Results")
            table.add_column("Phase", style="cyan")
            table.add_column("Status")
            table.add_column("Tokens", justify="right")
            table.add_column("Cost", justify="right")
            table.add_column("Artifact")

            for phase_result in result.phase_results:
                # Find phase name from workflow data
                phase_name = phase_result.phase_id
                for p in phases:
                    if p.get("phase_id") == phase_result.phase_id:
                        phase_name = p.get("name", phase_result.phase_id)
                        break

                status_icon = {
                    PhaseStatus.COMPLETED: "[green]✓[/green]",
                    PhaseStatus.FAILED: "[red]✗[/red]",
                    PhaseStatus.RUNNING: "[yellow]⋯[/yellow]",
                    PhaseStatus.PENDING: "[dim]○[/dim]",
                    PhaseStatus.SKIPPED: "[dim]-[/dim]",
                }.get(phase_result.status, "[dim]?[/dim]")

                table.add_row(
                    phase_name,
                    f"{status_icon} {phase_result.status.value}",
                    _format_tokens(phase_result.total_tokens),
                    _format_cost(phase_result.cost_usd),
                    phase_result.artifact_id[:8] + "..." if phase_result.artifact_id else "-",
                )

            console.print(table)

        # Summary metrics
        metrics = result.metrics
        console.print()
        console.print("[bold]Summary:[/bold]")
        console.print(f"  Phases:   {metrics.completed_phases}/{metrics.total_phases} completed")
        console.print(f"  Tokens:   {_format_tokens(metrics.total_tokens)}")
        console.print(f"  Cost:     {_format_cost(metrics.total_cost_usd)}")
        console.print(f"  Duration: {metrics.total_duration_seconds:.1f}s")

        if result.artifact_ids:
            console.print(f"\n[bold]Artifacts:[/bold] {len(result.artifact_ids)}")
            for artifact_id in result.artifact_ids[:5]:
                console.print(f"  • {artifact_id}")
            if len(result.artifact_ids) > 5:
                console.print(f"  [dim]... and {len(result.artifact_ids) - 5} more[/dim]")

        # Exit with error if failed
        if result.status == ExecutionStatus.FAILED:
            raise typer.Exit(1)

    # Run async execution
    try:
        asyncio.run(_execute())
    except Exception as e:
        console.print(f"[bold red]Execution failed:[/bold red] {e}")
        logger.error("Workflow execution failed", error=str(e))
        raise typer.Exit(1) from e


@app.command("status")
def workflow_status(
    workflow_id: Annotated[
        str,
        typer.Argument(help="Workflow ID (partial match supported)"),
    ],
) -> None:
    """Show execution status and history for a workflow.

    Example:
        aef workflow status research-workflow
    """
    from aef_adapters.storage import (
        get_artifact_repository,
        get_event_store,
        get_session_repository,
    )

    event_store = get_event_store()
    events = event_store.get_all_events()

    # Find the workflow
    workflow_events = [
        e
        for e in events
        if e.event_type == "WorkflowCreated" and e.aggregate_id.startswith(workflow_id)
    ]

    if not workflow_events:
        console.print(f"[red]No workflow found matching: {workflow_id}[/red]")
        raise typer.Exit(1)

    workflow_event = workflow_events[0]
    full_workflow_id = workflow_event.aggregate_id
    workflow_data = workflow_event.event_data

    console.print()
    console.print(
        Panel(
            f"[bold]{workflow_data.get('name', 'Unknown')}[/bold]\n"
            f"[dim]ID: {full_workflow_id}[/dim]\n"
            f"[dim]Type: {workflow_data.get('workflow_type', 'Unknown')}[/dim]",
            title="[cyan]Workflow Status[/cyan]",
            border_style="cyan",
        )
    )

    # Find related execution events
    execution_events = [
        e
        for e in events
        if e.aggregate_id == full_workflow_id
        and e.event_type
        in (
            "WorkflowExecutionStarted",
            "PhaseStarted",
            "PhaseCompleted",
            "WorkflowCompleted",
            "WorkflowFailed",
        )
    ]

    if not execution_events:
        console.print("\n[dim]No execution history found for this workflow.[/dim]")
        console.print("[dim]Run with: aef workflow run {workflow_id}[/dim]")
        return

    # Group by execution_id
    executions: dict[str, list[Any]] = {}
    for event in execution_events:
        exec_id = event.event_data.get("execution_id", "unknown")
        if exec_id not in executions:
            executions[exec_id] = []
        executions[exec_id].append(event)

    console.print(f"\n[bold]Executions:[/bold] {len(executions)}")

    for exec_id, exec_events in executions.items():
        # Determine status from events
        status = "unknown"
        for e in exec_events:
            if e.event_type == "WorkflowCompleted":
                status = "completed"
            elif e.event_type == "WorkflowFailed":
                status = "failed"
            elif e.event_type == "WorkflowExecutionStarted" and status == "unknown":
                status = "running"

        status_icon = {
            "completed": "[green]✓[/green]",
            "failed": "[red]✗[/red]",
            "running": "[yellow]⋯[/yellow]",
        }.get(status, "[dim]?[/dim]")

        console.print(f"\n  {status_icon} Execution: [cyan]{exec_id[:8]}...[/cyan]")

        # Show phases
        phase_events = [
            e for e in exec_events if e.event_type in ("PhaseStarted", "PhaseCompleted")
        ]
        if phase_events:
            phases_completed = sum(1 for e in phase_events if e.event_type == "PhaseCompleted")
            phases_started = sum(1 for e in phase_events if e.event_type == "PhaseStarted")
            console.print(f"     Phases: {phases_completed}/{phases_started}")

        # Show final metrics if completed
        for e in exec_events:
            if e.event_type == "WorkflowCompleted":
                data = e.event_data
                console.print(f"     Tokens: {_format_tokens(data.get('total_tokens', 0))}")
                if "total_cost_usd" in data:
                    console.print(
                        f"     Cost: {_format_cost(Decimal(str(data['total_cost_usd'])))}"
                    )
            elif e.event_type == "WorkflowFailed":
                console.print(
                    f"     [red]Error: {e.event_data.get('error_message', 'Unknown')}[/red]"
                )

    # Show sessions
    session_repo = get_session_repository()
    sessions = session_repo.get_by_workflow(full_workflow_id)
    if sessions:
        console.print(f"\n[bold]Sessions:[/bold] {len(sessions)}")
        for session in sessions[:5]:
            status_icon = (
                "[green]✓[/green]" if session.status.value == "completed" else "[red]✗[/red]"
            )
            console.print(f"  {status_icon} {session.id} - {session.phase_id or 'N/A'}")

    # Show artifacts
    artifact_repo = get_artifact_repository()
    artifacts = artifact_repo.get_by_workflow(full_workflow_id)
    if artifacts:
        console.print(f"\n[bold]Artifacts:[/bold] {len(artifacts)}")
        for artifact in artifacts[:5]:
            console.print(f"  • {artifact.id} ({artifact.artifact_type.value})")
