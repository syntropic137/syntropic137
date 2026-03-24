"""System CRUD commands — create, list, show, update, delete."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table

from syn_cli._output import console, format_timestamp
from syn_cli.commands._api_helpers import api_delete, api_get, api_post, api_put, build_params

app = typer.Typer(
    name="system",
    help="Manage systems and their observability",
    no_args_is_help=True,
)


@app.command("create")
def create(
    org: Annotated[str, typer.Option("--org", "-o", help="Organization ID")],
    name: Annotated[str, typer.Option("--name", "-n", help="System name")],
    description: Annotated[str, typer.Option("--description", "-d", help="Description")] = "",
    created_by: Annotated[str, typer.Option(help="Creator identifier")] = "cli",
) -> None:
    """Create a new system within an organization."""
    data = api_post(
        "/systems",
        json={
            "organization_id": org,
            "name": name,
            "description": description,
            "created_by": created_by,
        },
    )

    console.print(f"[green]System created:[/green] {data.get('system_id', '')}")
    console.print(f"  Name: {name}")


@app.command("list")
def list_systems(
    org: Annotated[
        str | None, typer.Option("--org", "-o", help="Filter by organization ID")
    ] = None,
) -> None:
    """List all systems, optionally filtered by organization."""
    params = build_params(organization_id=org)
    data = api_get("/systems", params=params)

    systems = data.get("systems", [])
    if not systems:
        console.print("[dim]No systems found.[/dim]")
        return

    table = Table(title=f"Systems ({data.get('total', len(systems))})")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Name")
    table.add_column("Description")
    table.add_column("Repos", justify="right")
    table.add_column("Created")

    for s in systems:
        table.add_row(
            s.get("system_id", "")[:12],
            s.get("name", ""),
            s.get("description") or "—",
            str(s.get("repo_count", 0)),
            format_timestamp(str(s.get("created_at") or "")),
        )
    console.print(table)


@app.command("show")
def show(
    system_id: Annotated[str, typer.Argument(help="System ID")],
) -> None:
    """Show system details."""
    s = api_get(f"/systems/{system_id}")

    console.print(f"[bold]System:[/bold] {s.get('name', '')}")
    console.print(f"  ID:           {s.get('system_id', '')}")
    console.print(f"  Organization: {s.get('organization_id', '')}")
    if s.get("description"):
        console.print(f"  Description:  {s['description']}")
    console.print(f"  Repos:        {s.get('repo_count', 0)}")
    console.print(f"  Created:      {format_timestamp(str(s.get('created_at') or ''))}")


@app.command("update")
def update(
    system_id: Annotated[str, typer.Argument(help="System ID")],
    name: Annotated[str | None, typer.Option("--name", "-n", help="New name")] = None,
    description: Annotated[
        str | None, typer.Option("--description", "-d", help="New description")
    ] = None,
) -> None:
    """Update a system's name or description."""
    if not name and description is None:
        from syn_cli._output import print_error

        print_error("Provide at least --name or --description.")
        raise typer.Exit(1)

    body: dict[str, str] = {}
    if name:
        body["name"] = name
    if description is not None:
        body["description"] = description

    api_put(f"/systems/{system_id}", json=body)
    console.print(f"[green]System updated:[/green] {system_id}")


@app.command("delete")
def delete(
    system_id: Annotated[str, typer.Argument(help="System ID")],
    force: Annotated[bool, typer.Option("--force", "-f", help="Skip confirmation")] = False,
) -> None:
    """Delete a system."""
    if not force and not typer.confirm(f"Delete system {system_id}?"):
        console.print("[dim]Aborted.[/dim]")
        raise typer.Exit(0)

    api_delete(f"/systems/{system_id}")
    console.print(f"[red]System deleted:[/red] {system_id}")
