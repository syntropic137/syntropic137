"""Workflow CRUD commands — create, list, show, validate."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 — Typer needs Path at runtime
from typing import Annotated

import typer
from rich.table import Table

from syn_cli._output import console, print_error
from syn_cli.client import get_client
from syn_cli.commands._api_helpers import api_delete, api_get, api_post, handle_connect_error
from syn_cli.commands._workflow_models import WorkflowDetail
from syn_cli.commands._workflow_resolver import WorkflowResolver

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
    """Create a new workflow."""
    data = api_post(
        "/workflows",
        json={
            "name": name,
            "workflow_type": workflow_type,
            "repository_url": repo_url,
            "repository_ref": repo_ref,
            "description": description,
        },
    )

    workflow_id = data.get("id") or data.get("workflow_id", "unknown")
    console.print(f"[bold green]Created workflow:[/bold green] [cyan]{name}[/cyan]")
    console.print(f"  ID: [dim]{workflow_id}[/dim]")
    console.print(f"  Type: [dim]{workflow_type}[/dim]")


@app.command("list")
def list_workflows(
    include_archived: Annotated[
        bool,
        typer.Option("--include-archived", help="Include archived workflows"),
    ] = False,
) -> None:
    """List all workflows in the system."""
    params: dict[str, str] = {}
    if include_archived:
        params["include_archived"] = "true"
    data = api_get("/workflows", params=params)

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


def _render_workflow_detail(detail: WorkflowDetail) -> None:
    """Print workflow detail to console."""
    console.print("\n[bold]Workflow Details[/bold]")
    console.print(f"  [dim]ID:[/dim] {detail.id}")
    console.print(f"  [dim]Name:[/dim] [cyan]{detail.name}[/cyan]")
    console.print(f"  [dim]Type:[/dim] {detail.workflow_type}")
    console.print(f"  [dim]Classification:[/dim] {detail.classification}")
    if detail.phases:
        console.print(f"\n  [bold]Phases ({len(detail.phases)}):[/bold]")
        for phase in detail.phases:
            console.print(f"    - {phase.get('name', 'unnamed')}")
    else:
        console.print("\n  [dim]No phases defined[/dim]")


@app.command("show")
def show_workflow(
    workflow_id: Annotated[str, typer.Argument(help="Workflow ID (partial match supported)")],
) -> None:
    """Show details of a specific workflow."""
    try:
        with get_client() as client:
            wf = WorkflowResolver(client).resolve(workflow_id)
            resp = client.get(f"/workflows/{wf.id}")
    except typer.Exit:
        raise
    except Exception:
        handle_connect_error()

    if resp.status_code != 200:
        print_error(f"Workflow not found: {resp.json().get('detail', '')}")
        raise typer.Exit(1)

    _render_workflow_detail(WorkflowDetail(**resp.json()))


@app.command("validate")
def validate_workflow(
    file: Annotated[Path, typer.Argument(help="YAML file to validate")],
) -> None:
    """Validate a workflow YAML file without creating it."""
    validation = api_post("/workflows/validate", json={"file": str(file)})

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


@app.command("delete")
def delete_workflow(
    workflow_id: Annotated[str, typer.Argument(help="Workflow ID (partial match supported)")],
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Skip confirmation prompt"),
    ] = False,
) -> None:
    """Archive (soft-delete) a workflow template.

    Archived workflows are hidden from 'syn workflow list' by default.
    Use 'syn workflow list --include-archived' to see them.
    """
    try:
        with get_client() as client:
            wf = WorkflowResolver(client).resolve(workflow_id)
    except typer.Exit:
        raise
    except Exception:
        handle_connect_error()

    if not force and not typer.confirm(f"Archive workflow '{wf.name}' ({wf.id})?"):
        console.print("[dim]Aborted.[/dim]")
        raise typer.Exit(0)

    api_delete(f"/workflows/{wf.id}")
    console.print(f"[bold green]Archived workflow:[/bold green] [cyan]{wf.name}[/cyan]")
    console.print(f"  ID: [dim]{wf.id}[/dim]")
