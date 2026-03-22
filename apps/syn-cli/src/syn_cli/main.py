"""Main CLI entry point for Syntropic137."""

from __future__ import annotations

import logging

import typer
from rich.console import Console

from syn_cli.client import get_api_url, get_client
from syn_cli.commands import (
    agent,
    artifacts,
    config,
    control,
    conversations,
    costs,
    events,
    execution,
    insights,
    metrics,
    observe,
    org,
    repo,
    sessions,
    system,
    triggers,
    watch,
    workflow,
)

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
app.add_typer(artifacts.app, name="artifacts")
app.add_typer(config.app, name="config")
app.add_typer(control.app, name="control")
app.add_typer(conversations.app, name="conversations")
app.add_typer(costs.app, name="costs")
app.add_typer(events.app, name="events")
app.add_typer(execution.app, name="execution")
app.add_typer(insights.app, name="insights")
app.add_typer(metrics.app, name="metrics")
app.add_typer(observe.app, name="observe")
app.add_typer(org.app, name="org")
app.add_typer(repo.app, name="repo")
app.add_typer(sessions.app, name="sessions")
app.add_typer(system.app, name="system")
app.add_typer(triggers.app, name="triggers")
app.add_typer(watch.app, name="watch")


@app.command()
def health() -> None:
    """Check API server health status."""
    from syn_cli._output import console, print_error

    try:
        with get_client() as client:
            resp = client.get("/health")
    except Exception:
        print_error(f"Could not connect to API at {get_api_url()}")
        console.print("[dim]Make sure the API server is running.[/dim]")
        raise typer.Exit(1) from None

    if resp.status_code != 200:
        print_error(f"Health check failed: HTTP {resp.status_code}")
        raise typer.Exit(1)

    data = resp.json()
    status = data.get("status", "unknown")
    mode = data.get("mode", "unknown")

    if status == "healthy" and mode == "full":
        console.print("[bold green]Healthy[/bold green] — all systems operational")
    elif status == "healthy":
        console.print(f"[bold yellow]Degraded[/bold yellow] — mode: {mode}")
        for reason in data.get("degraded_reasons", []):
            console.print(f"  [yellow]• {reason}[/yellow]")
    else:
        console.print(f"[bold red]Unhealthy[/bold red] — status: {status}")
        raise typer.Exit(1)

    sub = data.get("subscription")
    if sub:
        console.print("  [dim]Event store: connected[/dim]")
        console.print(f"  [dim]Subscription: {sub.get('status', 'unknown')}[/dim]")


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
    workflow.run_workflow(workflow_id, inputs=inputs, dry_run=dry_run, quiet=quiet)


if __name__ == "__main__":
    app()
