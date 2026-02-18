"""Main CLI entry point for Syntropic137."""

from __future__ import annotations

import logging

import typer
from rich.console import Console

from syn_cli.commands import agent, config, control, triggers, workflow

# Basic logging setup (no syn_shared dependency)
logging.basicConfig(level=logging.WARNING, format="%(message)s")

# Create CLI app
app = typer.Typer(
    name="syn",
    help="Syntropic137 - Event-sourced workflow engine for AI agents",
    add_completion=False,
)
console = Console()

# Register subcommands
app.add_typer(workflow.app, name="workflow")
app.add_typer(agent.app, name="agent")
app.add_typer(config.app, name="config")
app.add_typer(control.app, name="control")
app.add_typer(triggers.app, name="triggers")


@app.command()
def version() -> None:
    """Show version information."""
    from syn_cli import __version__

    console.print(f"[bold]Syntropic137[/bold] v{__version__}")


@app.command("run")
def run_shortcut(
    workflow_id: str = typer.Argument(..., help="Workflow ID to execute"),
    inputs: list[str] | None = typer.Option(
        None, "--input", "-i", help="Input variables as key=value"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Validate without executing"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Minimal output"),
) -> None:
    """Execute a workflow (shortcut for 'syn workflow run')."""
    workflow.run_workflow(workflow_id, inputs, dry_run, quiet)


if __name__ == "__main__":
    app()
