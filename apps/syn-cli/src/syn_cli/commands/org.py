"""Organization management commands — create, list, show, update, delete."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table

from syn_cli._output import console, format_timestamp, print_error
from syn_cli.commands._api_helpers import api_delete, api_get, api_post, api_put, build_params

app = typer.Typer(
    name="org",
    help="Manage organizations",
    no_args_is_help=True,
)


@app.command("create")
def create(
    name: Annotated[str, typer.Option("--name", "-n", help="Organization name")],
    slug: Annotated[str, typer.Option("--slug", "-s", help="URL-safe slug")],
    created_by: Annotated[str, typer.Option(help="Creator identifier")] = "cli",
) -> None:
    """Create a new organization."""
    data = api_post(
        "/organizations",
        json={"name": name, "slug": slug, "created_by": created_by},
    )
    console.print(f"[green]Organization created:[/green] {data.get('organization_id', '')}")
    console.print(f"  Name: {name}  Slug: {slug}")


@app.command("list")
def list_orgs() -> None:
    """List all organizations."""
    data = api_get("/organizations")

    orgs = data.get("organizations", [])
    if not orgs:
        console.print("[dim]No organizations found.[/dim]")
        return

    table = Table(title=f"Organizations ({data.get('total', len(orgs))})")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Name")
    table.add_column("Slug")
    table.add_column("Systems", justify="right")
    table.add_column("Repos", justify="right")
    table.add_column("Created")

    for o in orgs:
        table.add_row(
            o.get("organization_id", "")[:12],
            o.get("name", ""),
            o.get("slug", ""),
            str(o.get("system_count", 0)),
            str(o.get("repo_count", 0)),
            format_timestamp(str(o.get("created_at") or "")),
        )
    console.print(table)


@app.command("show")
def show(
    organization_id: Annotated[str, typer.Argument(help="Organization ID")],
) -> None:
    """Show details of an organization."""
    o = api_get(f"/organizations/{organization_id}")

    console.print(f"[bold]Organization:[/bold] {o.get('name', '')}")
    console.print(f"  ID:       {o.get('organization_id', '')}")
    console.print(f"  Slug:     {o.get('slug', '')}")
    console.print(f"  Systems:  {o.get('system_count', 0)}")
    console.print(f"  Repos:    {o.get('repo_count', 0)}")
    console.print(f"  Created:  {format_timestamp(str(o.get('created_at') or ''))}")


@app.command("update")
def update(
    organization_id: Annotated[str, typer.Argument(help="Organization ID")],
    name: Annotated[str | None, typer.Option("--name", "-n", help="New name")] = None,
    slug: Annotated[str | None, typer.Option("--slug", "-s", help="New slug")] = None,
) -> None:
    """Update an organization's name or slug."""
    if not name and not slug:
        print_error("Provide at least --name or --slug.")
        raise typer.Exit(1)

    body = build_params(name=name, slug=slug)
    api_put(f"/organizations/{organization_id}", json=body)
    console.print(f"[green]Organization updated:[/green] {organization_id}")


@app.command("delete")
def delete(
    organization_id: Annotated[str, typer.Argument(help="Organization ID")],
    force: Annotated[bool, typer.Option("--force", "-f", help="Skip confirmation")] = False,
) -> None:
    """Delete an organization."""
    if not force and not typer.confirm(f"Delete organization {organization_id}?"):
        console.print("[dim]Aborted.[/dim]")
        raise typer.Exit(0)

    api_delete(f"/organizations/{organization_id}")
    console.print(f"[red]Organization deleted:[/red] {organization_id}")
