"""Main CLI entry point for Agentic Engineering Framework."""

import typer
from rich.console import Console

from aef_cli.commands import workflow
from aef_shared.logging import LogConfig, configure_logging, get_logger

# Configure logging
configure_logging(LogConfig())
logger = get_logger(__name__)

# Create CLI app
app = typer.Typer(
    name="aef",
    help="Agentic Engineering Framework - Event-sourced workflow engine for AI agents",
    add_completion=False,
)
console = Console()

# Register subcommands
app.add_typer(workflow.app, name="workflow")


@app.command()
def run(
    workflow_name: str = typer.Argument(..., help="Name or ID of the workflow to execute"),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Show what would be done"),
) -> None:
    """Execute a workflow."""
    logger.info("Starting workflow", workflow=workflow_name, dry_run=dry_run)
    console.print(f"[bold blue]Starting workflow:[/bold blue] {workflow_name}")

    if dry_run:
        console.print("[yellow]Dry run mode - no changes will be made[/yellow]")
        return

    # TODO: Implement workflow execution
    console.print("[green]✓ Workflow started[/green]")


@app.command()
def seed(
    path: str | None = typer.Option(None, "--path", "-p", help="Path to workflow YAML files"),
) -> None:
    """Seed workflow definitions from YAML files."""
    logger.info("Seeding workflows", path=path)

    if path:
        console.print(f"[blue]Loading workflows from:[/blue] {path}")
    else:
        console.print("[blue]Loading workflows from default location[/blue]")

    # TODO: Implement workflow seeding
    console.print("[green]✓ Workflows seeded[/green]")


@app.command()
def version() -> None:
    """Show version information."""
    from aef_cli import __version__

    console.print(f"[bold]Agentic Engineering Framework[/bold] v{__version__}")


if __name__ == "__main__":
    app()
