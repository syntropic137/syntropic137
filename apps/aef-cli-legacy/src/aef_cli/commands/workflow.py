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
    from aef_domain.contexts.orchestration._shared.WorkflowValueObjects import (
        PhaseDefinition,
        WorkflowClassification,
        WorkflowType,
    )
    from aef_domain.contexts.orchestration.domain.commands.CreateWorkflowTemplateCommand import (
        CreateWorkflowTemplateCommand,
    )
    from aef_domain.contexts.orchestration.slices.create_workflow_template.CreateWorkflowTemplateHandler import (
        CreateWorkflowTemplateHandler,
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
    command = CreateWorkflowTemplateCommand(
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
    handler = CreateWorkflowTemplateHandler(
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
    import asyncio

    from aef_adapters.storage import (
        connect_event_store,
        disconnect_event_store,
        get_event_store_client,
        get_workflow_repository,
    )
    from aef_shared.settings import get_settings

    settings = get_settings()

    # For test environment, use in-memory repository (sync API)
    if settings.is_test:
        repo = get_workflow_repository()
        workflows_data = [
            {
                "id": w.id,
                "name": w.name,
                "workflow_type": w._workflow_type.value,
                "status": w._status.value,
            }
            for w in repo.get_all()
        ]
    else:
        # For dev/prod, read from event store (async API)
        async def _get_workflows() -> list[dict]:
            await connect_event_store()
            try:
                client = get_event_store_client()
                events = await client.read_all_events_from(after_global_nonce=0, limit=10000)
                workflow_events = [
                    e for e in events if e.event.event_type == "WorkflowTemplateCreated"
                ]
                return [
                    {
                        "id": e.metadata.aggregate_id,
                        "name": e.event.model_dump().get("name", "Unknown"),
                        "workflow_type": e.event.model_dump().get("workflow_type", "Unknown"),
                        "status": "pending",  # Default status
                    }
                    for e in workflow_events
                ]
            finally:
                await disconnect_event_store()

        workflows_data = asyncio.run(_get_workflows())

    if not workflows_data:
        console.print("[dim]No workflows found. Create one with:[/dim]")
        console.print('  [cyan]aef workflow create "My Workflow"[/cyan]')
        return

    # Display as table
    table = Table(title="Workflows")
    table.add_column("ID", style="dim")
    table.add_column("Name", style="cyan")
    table.add_column("Type", style="green")
    table.add_column("Status", style="yellow")

    for wf in workflows_data:
        table.add_row(
            wf["id"][:8] + "...",
            wf["name"],
            wf["workflow_type"],
            wf["status"],
        )

    console.print(table)


@app.command("show")
def show_workflow(
    workflow_id: Annotated[str, typer.Argument(help="Workflow ID (partial match supported)")],
) -> None:
    """Show details of a specific workflow."""
    import asyncio

    from aef_adapters.storage import (
        connect_event_store,
        disconnect_event_store,
        get_event_store_client,
        get_workflow_repository,
    )
    from aef_shared.settings import get_settings

    settings = get_settings()

    # For test environment, use in-memory repository (sync API)
    if settings.is_test:
        repo = get_workflow_repository()
        workflows = repo.get_all()
        matching = [w for w in workflows if w.id.startswith(workflow_id)]

        if not matching:
            console.print(f"[red]No workflow found matching: {workflow_id}[/red]")
            raise typer.Exit(1)

        workflow = matching[0]
        workflow_data = {
            "id": workflow.id,
            "name": workflow.name,
            "workflow_type": workflow._workflow_type.value,
            "status": workflow._status.value,
            "classification": workflow._classification.value,
            "phases": [{"name": p.name} for p in workflow._phases],
        }
    else:
        # For dev/prod, read from event store (async API)
        async def _get_workflow() -> dict[str, Any] | None:
            await connect_event_store()
            try:
                client = get_event_store_client()
                events = await client.read_all_events_from(after_global_nonce=0, limit=10000)
                matching = [
                    e
                    for e in events
                    if e.event.event_type == "WorkflowTemplateCreated"
                    and e.metadata.aggregate_id.startswith(workflow_id)
                ]

                if not matching:
                    return None

                event = matching[0]
                data = event.event.model_dump()
                return {
                    "id": event.metadata.aggregate_id,
                    "name": data.get("name", "Unknown"),
                    "workflow_type": data.get("workflow_type", "Unknown"),
                    "status": "pending",
                    "classification": data.get("classification", "Unknown"),
                    "phases": data.get("phases", []),
                }
            finally:
                await disconnect_event_store()

        workflow_data = asyncio.run(_get_workflow())  # type: ignore[arg-type]

    if workflow_data is None:
        console.print(f"[red]No workflow found matching: {workflow_id}[/red]")
        raise typer.Exit(1)

    console.print("\n[bold]Workflow Details[/bold]")
    console.print(f"  [dim]ID:[/dim] {workflow_data['id']}")
    console.print(f"  [dim]Name:[/dim] [cyan]{workflow_data['name']}[/cyan]")
    console.print(f"  [dim]Type:[/dim] {workflow_data['workflow_type']}")
    console.print(f"  [dim]Status:[/dim] {workflow_data['status']}")
    console.print(f"  [dim]Classification:[/dim] {workflow_data['classification']}")

    phases = workflow_data.get("phases", [])
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
    from aef_domain.contexts.orchestration.seed_workflow import WorkflowSeeder
    from aef_domain.contexts.orchestration.slices.create_workflow_template.CreateWorkflowTemplateHandler import (
        CreateWorkflowTemplateHandler,
    )

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
            handler = CreateWorkflowTemplateHandler(
                repository=repository, event_publisher=publisher
            )
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
    from aef_domain.contexts.orchestration._shared.workflow_definition import (
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
    container: Annotated[
        bool,
        typer.Option(
            "--container/--no-container",
            "-c",
            help="Run agent inside isolated container (default: True per ADR-021)",
        ),
    ] = True,
    tenant_id: Annotated[
        str | None,
        typer.Option(
            "--tenant",
            help="Tenant ID for multi-tenant token attribution",
        ),
    ] = None,
) -> None:
    """Execute a workflow.

    By default, agents run inside isolated containers (per ADR-021/ADR-023).

    Examples:
        # Run workflow with inputs (runs in container by default)
        aef workflow run research-workflow --input topic="AI agents" --input depth=3

        # Dry run to validate
        aef workflow run research-workflow --dry-run

        # Run quietly (minimal output)
        aef workflow run research-workflow --quiet

        # Disable container mode (legacy, not recommended)
        aef workflow run research-workflow --no-container --input topic="test"
    """
    from aef_adapters.agents import (
        AgentProtocol,
        AgentProvider,
        # InstrumentedAgent removed - observability via ADR-029
        MockAgent,
        MockAgentConfig,
    )

    # Hooks removed - observability via ADR-029
    from aef_adapters.storage import (
        connect_event_store,
        disconnect_event_store,
        get_artifact_repository,
        get_event_store_client,
        get_session_repository,
        get_workflow_repository,
    )
    from aef_domain.contexts.orchestration._shared.ExecutionValueObjects import (
        ExecutionStatus,
        PhaseStatus,
    )
    from aef_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionEngine import (
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

    # Result container for async -> sync communication
    result_container: dict[str, Any] = {}

    async def _find_workflow_async() -> tuple[str, dict, str, list] | None:
        """Find workflow by ID prefix using the event store."""
        from aef_shared.settings import get_settings

        settings = get_settings()

        if settings.is_test:
            # For test environment, use in-memory repository (sync API)
            repo = get_workflow_repository()
            all_workflows = repo.get_all()
        else:
            # For dev/prod, read from event store (async API)
            await connect_event_store()
            try:
                client = get_event_store_client()
                events = await client.read_all_events_from(after_global_nonce=0, limit=10000)
                workflow_events = [
                    e for e in events if e.event.event_type == "WorkflowTemplateCreated"
                ]
                # Create simple workflow-like objects from events
                all_workflows = []
                for e in workflow_events:
                    event_data = e.event.model_dump()

                    # Create a simple namespace object with required attributes
                    class WorkflowData:
                        def __init__(self, data: dict, agg_id: str) -> None:
                            self.id = agg_id
                            self.name = data.get("name", "Unknown")
                            self._workflow_type = type(
                                "WfType", (), {"value": data.get("workflow_type", "unknown")}
                            )()
                            self._status = type("Status", (), {"value": "pending"})()
                            # Build phases from event data
                            phases_raw = data.get("phases", [])
                            self._phases = [
                                type(
                                    "Phase",
                                    (),
                                    {
                                        "phase_id": p.get("phase_id", f"phase-{i}"),
                                        "name": p.get("name", f"Phase {i}"),
                                        "order": p.get("order", i),
                                        "description": p.get("description", ""),
                                    },
                                )()
                                for i, p in enumerate(phases_raw, 1)
                            ]

                    all_workflows.append(WorkflowData(event_data, e.metadata.aggregate_id))
            finally:
                await disconnect_event_store()

        # Find matching workflows by ID prefix
        matching = [w for w in all_workflows if w.id.startswith(workflow_id)]

        if not matching:
            return None

        if len(matching) > 1:
            result_container["multiple_matches"] = [(w.id, w.name) for w in matching[:5]]
            return None

        workflow = matching[0]
        # Convert phases to dict format
        phases_data = [
            {
                "phase_id": p.phase_id,
                "name": p.name,
                "order": p.order,
                "description": p.description,
            }
            for p in workflow._phases
        ]
        return (
            workflow.id,
            {"name": workflow.name},
            workflow.name,
            phases_data,
        )

    # Run the async workflow lookup
    workflow_info = asyncio.run(_find_workflow_async())

    if workflow_info is None:
        if "multiple_matches" in result_container:
            console.print(f"[yellow]Multiple workflows match '{workflow_id}':[/yellow]")
            for wf_id, wf_name in result_container["multiple_matches"]:
                console.print(f"  • {wf_id[:8]}... - {wf_name}")
            console.print("[dim]Please provide a more specific ID[/dim]")
        else:
            console.print(f"[red]No workflow found matching: {workflow_id}[/red]")
            console.print("[dim]Use 'aef workflow list' to see available workflows[/dim]")
        raise typer.Exit(1)

    full_workflow_id, _workflow_data, workflow_name, phases = workflow_info

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

    if container:
        console.print("\n[bold cyan]🐳 Container Mode[/bold cyan]")
        console.print("  Agent will run in isolated Docker container with sidecar proxy")
        if tenant_id:
            console.print(f"  Tenant: [dim]{tenant_id}[/dim]")

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
        """Execute workflow asynchronously with proper event store connection."""
        # Connect to event store first
        await connect_event_store()

        try:
            # Get repositories (they use the connected event store client)
            workflow_repo = get_workflow_repository()
            session_repo = get_session_repository()
            artifact_repo = get_artifact_repository()

            # Create agent factory - REQUIRES API keys (fail fast)
            def agent_factory(provider: str) -> AgentProtocol:
                """Create an instrumented agent for the given provider.

                REQUIRES real agent API keys. Fails fast if not configured.
                MockAgent is ONLY available in test environment (APP_ENVIRONMENT=test).
                """
                from aef_adapters.agents import get_agent
                from aef_shared.settings import get_settings

                settings = get_settings()

                # In test mode, MockAgent is allowed
                base_agent: AgentProtocol
                if settings.is_test and provider == "mock":
                    mock_config = MockAgentConfig(
                        default_response=f"Mock response for {provider} agent execution."
                    )
                    base_agent = MockAgent(mock_config)
                    console.print("[dim]Using MockAgent (test mode)[/dim]")
                # Default to Claude if provider is 'mock' but we're not in test
                elif provider == "mock":
                    # Treat 'mock' as 'claude' in non-test environments
                    if not settings.anthropic_api_key:
                        console.print(
                            "[bold red]Error:[/bold red] ANTHROPIC_API_KEY is required. "
                            "Add it to your .env file at the project root."
                        )
                        raise typer.Exit(1)
                    base_agent = get_agent(AgentProvider.CLAUDE)
                    console.print("[dim]Using Claude agent[/dim]")
                elif provider == "claude":
                    if not settings.anthropic_api_key:
                        console.print(
                            "[bold red]Error:[/bold red] ANTHROPIC_API_KEY is required for Claude agent. "
                            "Add it to your .env file at the project root."
                        )
                        raise typer.Exit(1)
                    base_agent = get_agent(AgentProvider.CLAUDE)
                    console.print("[dim]Using Claude agent[/dim]")
                elif provider == "openai":
                    if not settings.openai_api_key:
                        console.print(
                            "[bold red]Error:[/bold red] OPENAI_API_KEY is required for OpenAI agent. "
                            "Add it to your .env file at the project root."
                        )
                        raise typer.Exit(1)
                    base_agent = get_agent(AgentProvider.OPENAI)
                    console.print("[dim]Using OpenAI agent[/dim]")
                else:
                    console.print(
                        f"[bold red]Error:[/bold red] Unknown agent provider: {provider}. "
                        f"Supported: claude, openai"
                    )
                    raise typer.Exit(1)

                # Observability handled by EventBuffer/AgentEventStore at executor level (ADR-029)
                return base_agent

            # Create engine with ADR-023 compliant dependencies
            from aef_adapters.events import get_event_store
            from aef_adapters.projections.manager import get_projection_manager
            from aef_adapters.storage.artifact_storage import get_artifact_storage
            from aef_adapters.storage.repositories import get_workflow_execution_repository
            from aef_adapters.workspace_backends.service import WorkspaceService
            from aef_domain.contexts.artifacts import ArtifactQueryService

            execution_repo = get_workflow_execution_repository()
            event_store = get_event_store()
            artifact_content_storage = await get_artifact_storage()

            # Initialize event store (creates TimescaleDB schema)
            # ADR-029: Simplified event system
            await event_store.initialize()

            # Get artifact query service for multi-phase workflows
            manager = get_projection_manager()
            artifact_query = ArtifactQueryService(manager.artifact_list)

            # Container environment - non-sensitive config only (ADR-024)
            #
            # Secrets are handled by the Setup Phase Secrets pattern:
            # 1. Engine generates GitHub App installation token (short-lived)
            # 2. Runs setup script inside container WITH token
            # 3. Clears token from environment BEFORE agent runs
            # 4. Agent uses cached git/gh credentials (no raw token access)
            #
            # ANTHROPIC_API_KEY is passed to agent (needed for Claude calls)
            # GitHub auth is EXCLUSIVELY via GitHub App (no GH_TOKEN/PAT)
            # See ADR-024: Setup Phase Secrets Pattern
            container_env: dict[str, str] = {}

            workspace_service = WorkspaceService.create(environment=container_env)

            engine = WorkflowExecutionEngine(
                workflow_repository=workflow_repo,
                execution_repository=execution_repo,
                workspace_service=workspace_service,
                session_repository=session_repo,
                artifact_repository=artifact_repo,
                agent_factory=agent_factory,
                observability_writer=event_store,  # ADR-029: Use AgentEventStore
                artifact_query_service=artifact_query,  # For multi-phase prompt injection
                artifact_content_storage=artifact_content_storage,  # ADR-012
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
                            use_container=container,
                            tenant_id=tenant_id,
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
                        use_container=container,
                        tenant_id=tenant_id,
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

                    status_icons = {
                        PhaseStatus.COMPLETED: "[green]✓[/green]",
                        PhaseStatus.FAILED: "[red]✗[/red]",
                        PhaseStatus.RUNNING: "[yellow]⋯[/yellow]",
                        PhaseStatus.PENDING: "[dim]○[/dim]",
                        PhaseStatus.SKIPPED: "[dim]-[/dim]",
                    }
                    status_icon = status_icons.get(PhaseStatus(phase_result.status), "[dim]?[/dim]")

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
            console.print(
                f"  Phases:   {metrics.completed_phases}/{metrics.total_phases} completed"
            )
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
        finally:
            # Always disconnect from event store
            await disconnect_event_store()

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
    from aef_adapters.storage import get_workflow_repository

    # Find workflow using repository (works for both test and prod)
    repo = get_workflow_repository()
    all_workflows = repo.get_all()

    # Find matching workflows by ID prefix
    matching = [w for w in all_workflows if w.id.startswith(workflow_id)]

    if not matching:
        console.print(f"[red]No workflow found matching: {workflow_id}[/red]")
        console.print("[dim]Use 'aef workflow list' to see available workflows[/dim]")
        raise typer.Exit(1)

    workflow = matching[0]
    full_workflow_id = workflow.id
    workflow_data = {
        "name": workflow.name,
        "workflow_type": workflow._workflow_type.value,
        "classification": workflow._classification.value,
        "phases": [
            {
                "phase_id": p.phase_id,
                "name": p.name,
                "order": p.order,
                "description": p.description,
            }
            for p in workflow._phases
        ],
    }

    # Display workflow info
    console.print()
    console.print(
        Panel(
            f"[bold]{workflow_data.get('name', 'Unknown')}[/bold]\n"
            f"[dim]ID: {full_workflow_id}[/dim]\n"
            f"[dim]Type: {workflow_data.get('workflow_type', 'Unknown')}[/dim]\n"
            f"[dim]Status: {workflow._status.value}[/dim]",
            title="[cyan]Workflow Status[/cyan]",
            border_style="cyan",
        )
    )

    # Show phases
    phases = workflow_data.get("phases", [])
    if phases:
        console.print(f"\n[bold]Phases:[/bold] {len(phases)}")
        for phase in phases:
            console.print(f"  • {phase['name']} ({phase['phase_id']})")

    # Note: Execution history requires event store access
    console.print("\n[dim]No execution history available.[/dim]")
    console.print(f"[dim]Run with: aef workflow run {workflow_id}[/dim]")
