"""Main CLI entry point for Agentic Engineering Framework."""

import typer
from rich.console import Console

from aef_cli.commands import agent, config, control, workflow
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
app.add_typer(agent.app, name="agent")
app.add_typer(config.app, name="config")
app.add_typer(control.app, name="control")


@app.command()
def version() -> None:
    """Show version information."""
    from aef_cli import __version__

    console.print(f"[bold]Agentic Engineering Framework[/bold] v{__version__}")


# Convenience alias: `aef run` delegates to `aef workflow run`
@app.command("run")
def run_shortcut(
    workflow_id: str = typer.Argument(..., help="Workflow ID to execute"),
    inputs: list[str] | None = typer.Option(
        None, "--input", "-i", help="Input variables as key=value"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Validate without executing"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Minimal output"),
) -> None:
    """Execute a workflow (shortcut for 'aef workflow run')."""
    # Delegate to workflow run command
    workflow.run_workflow(workflow_id, inputs, dry_run, quiet)


if __name__ == "__main__":
    app()
