"""System management commands — CRUD plus status, cost, activity, patterns, history."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table

from syn_cli._output import (
    console,
    format_cost,
    format_timestamp,
    format_tokens,
    print_error,
    status_style,
)
from syn_cli.client import get_client

app = typer.Typer(
    name="system",
    help="Manage systems and their observability",
    no_args_is_help=True,
)


def _handle_connect_error() -> None:
    from syn_cli.client import get_api_url

    print_error(f"Could not connect to API at {get_api_url()}")
    console.print("[dim]Make sure the API server is running.[/dim]")
    raise typer.Exit(1)


@app.command("create")
def create(
    org: Annotated[str, typer.Option("--org", "-o", help="Organization ID")],
    name: Annotated[str, typer.Option("--name", "-n", help="System name")],
    description: Annotated[str, typer.Option("--description", "-d", help="Description")] = "",
    created_by: Annotated[str, typer.Option(help="Creator identifier")] = "cli",
) -> None:
    """Create a new system within an organization."""
    try:
        with get_client() as client:
            resp = client.post(
                "/systems",
                json={
                    "organization_id": org,
                    "name": name,
                    "description": description,
                    "created_by": created_by,
                },
            )
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code != 200:
        print_error(resp.json().get("detail", f"HTTP {resp.status_code}"))
        raise typer.Exit(1)

    data = resp.json()
    console.print(f"[green]System created:[/green] {data.get('system_id', '')}")
    console.print(f"  Name: {name}")


@app.command("list")
def list_systems(
    org: Annotated[
        str | None, typer.Option("--org", "-o", help="Filter by organization ID")
    ] = None,
) -> None:
    """List all systems, optionally filtered by organization."""
    try:
        with get_client() as client:
            params: dict[str, str] = {}
            if org:
                params["organization_id"] = org
            resp = client.get("/systems", params=params)
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code != 200:
        print_error(resp.json().get("detail", f"HTTP {resp.status_code}"))
        raise typer.Exit(1)

    data = resp.json()
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
    try:
        with get_client() as client:
            resp = client.get(f"/systems/{system_id}")
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code == 404:
        print_error(f"System not found: {system_id}")
        raise typer.Exit(1)
    if resp.status_code != 200:
        print_error(resp.json().get("detail", f"HTTP {resp.status_code}"))
        raise typer.Exit(1)

    s = resp.json()
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
        print_error("Provide at least --name or --description.")
        raise typer.Exit(1)

    body: dict[str, str] = {}
    if name:
        body["name"] = name
    if description is not None:
        body["description"] = description

    try:
        with get_client() as client:
            resp = client.put(f"/systems/{system_id}", json=body)
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code == 404:
        print_error(f"System not found: {system_id}")
        raise typer.Exit(1)
    if resp.status_code != 200:
        print_error(resp.json().get("detail", f"HTTP {resp.status_code}"))
        raise typer.Exit(1)

    console.print(f"[green]System updated:[/green] {system_id}")


@app.command("delete")
def delete(
    system_id: Annotated[str, typer.Argument(help="System ID")],
    force: Annotated[bool, typer.Option("--force", "-f", help="Skip confirmation")] = False,
) -> None:
    """Delete a system."""
    if not force:
        if not typer.confirm(f"Delete system {system_id}?"):
            console.print("[dim]Aborted.[/dim]")
            raise typer.Exit(0)

    try:
        with get_client() as client:
            resp = client.delete(f"/systems/{system_id}")
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code == 404:
        print_error(f"System not found: {system_id}")
        raise typer.Exit(1)
    if resp.status_code == 409:
        print_error(resp.json().get("detail", "Conflict — system may have repos or be deleted."))
        raise typer.Exit(1)
    if resp.status_code != 200:
        print_error(resp.json().get("detail", f"HTTP {resp.status_code}"))
        raise typer.Exit(1)

    console.print(f"[red]System deleted:[/red] {system_id}")


@app.command("status")
def system_status(
    system_id: Annotated[str, typer.Argument(help="System ID")],
) -> None:
    """Show health status of a system and its repos."""
    try:
        with get_client() as client:
            resp = client.get(f"/systems/{system_id}/status")
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code == 404:
        print_error(f"System not found: {system_id}")
        raise typer.Exit(1)
    if resp.status_code != 200:
        print_error(resp.json().get("detail", f"HTTP {resp.status_code}"))
        raise typer.Exit(1)

    d = resp.json()
    overall = d.get("overall_status", "")
    style = status_style(overall)
    console.print(f"[bold]{d.get('system_name', system_id)}[/bold]")
    console.print(f"  Status: [{style}]{overall}[/{style}]" if style else f"  Status: {overall}")
    console.print(
        f"  Repos:  {d.get('total_repos', 0)}  "
        f"healthy={d.get('healthy_repos', 0)}  "
        f"degraded={d.get('degraded_repos', 0)}  "
        f"failing={d.get('failing_repos', 0)}"
    )

    repos = d.get("repos", [])
    if repos:
        console.print()
        table = Table(title="Repo Health", show_edge=False)
        table.add_column("Repo", style="cyan")
        table.add_column("Status")
        table.add_column("Success Rate", justify="right")
        table.add_column("Active", justify="right")
        table.add_column("Last Run")
        for r in repos:
            rs = r.get("status", "")
            rstyle = status_style(rs)
            rate = r.get("success_rate")
            table.add_row(
                r.get("repo_full_name", ""),
                f"[{rstyle}]{rs}[/{rstyle}]" if rstyle else rs,
                f"{rate:.0%}" if rate is not None else "—",
                str(r.get("active_executions", 0)),
                format_timestamp(r.get("last_execution_at")),
            )
        console.print(table)


@app.command("cost")
def system_cost(
    system_id: Annotated[str, typer.Argument(help="System ID")],
) -> None:
    """Show cost breakdown for a system."""
    try:
        with get_client() as client:
            resp = client.get(f"/systems/{system_id}/cost")
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code == 404:
        print_error(f"System not found: {system_id}")
        raise typer.Exit(1)
    if resp.status_code != 200:
        print_error(resp.json().get("detail", f"HTTP {resp.status_code}"))
        raise typer.Exit(1)

    d = resp.json()
    console.print(f"[bold]{d.get('system_name', system_id)} — Cost[/bold]")
    console.print(f"  Total cost:    {format_cost(d.get('total_cost_usd') or '0')}")
    console.print(f"  Total tokens:  {format_tokens(d.get('total_tokens') or 0)}")
    console.print(f"  Executions:    {d.get('execution_count', 0)}")

    if d.get("cost_by_repo"):
        console.print()
        table = Table(title="By Repo", show_edge=False)
        table.add_column("Repo", style="cyan")
        table.add_column("Cost", justify="right")
        for repo, c in sorted(d["cost_by_repo"].items(), key=lambda x: x[1], reverse=True):
            table.add_row(repo, format_cost(c))
        console.print(table)


@app.command("activity")
def system_activity(
    system_id: Annotated[str, typer.Argument(help="System ID")],
    limit: Annotated[int, typer.Option(help="Max entries")] = 50,
    offset: Annotated[int, typer.Option(help="Pagination offset")] = 0,
) -> None:
    """Show recent execution activity for a system."""
    try:
        with get_client() as client:
            resp = client.get(
                f"/systems/{system_id}/activity",
                params={"limit": limit, "offset": offset},
            )
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code == 404:
        print_error(f"System not found: {system_id}")
        raise typer.Exit(1)
    if resp.status_code != 200:
        print_error(resp.json().get("detail", f"HTTP {resp.status_code}"))
        raise typer.Exit(1)

    data = resp.json()
    entries = data.get("entries", [])
    if not entries:
        console.print("[dim]No activity found.[/dim]")
        return

    table = Table(title=f"System Activity ({data.get('total', 0)} total)")
    table.add_column("Execution", style="cyan", no_wrap=True)
    table.add_column("Workflow")
    table.add_column("Status")
    table.add_column("Started")
    table.add_column("Trigger")

    for e in entries:
        s = e.get("status", "")
        style = status_style(s)
        table.add_row(
            e.get("execution_id", "")[:12],
            e.get("workflow_name", ""),
            f"[{style}]{s}[/{style}]" if style else s,
            format_timestamp(e.get("started_at")),
            e.get("trigger_source") or "—",
        )
    console.print(table)


@app.command("patterns")
def system_patterns(
    system_id: Annotated[str, typer.Argument(help="System ID")],
) -> None:
    """Show failure patterns and cost outliers for a system."""
    try:
        with get_client() as client:
            resp = client.get(f"/systems/{system_id}/patterns")
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code == 404:
        print_error(f"System not found: {system_id}")
        raise typer.Exit(1)
    if resp.status_code != 200:
        print_error(resp.json().get("detail", f"HTTP {resp.status_code}"))
        raise typer.Exit(1)

    d = resp.json()
    console.print(
        f"[bold]{d.get('system_name', system_id)} — Patterns[/bold]  "
        f"[dim](last {d.get('analysis_window_hours', 168)}h)[/dim]"
    )

    failures = d.get("failure_patterns", [])
    if failures:
        console.print()
        table = Table(title="Failure Patterns", show_edge=False)
        table.add_column("Error Type", style="red")
        table.add_column("Count", justify="right")
        table.add_column("Affected Repos")
        table.add_column("Last Seen")
        for fp in failures:
            repos = ", ".join(fp.get("affected_repos", []))
            table.add_row(
                fp.get("error_type", ""),
                str(fp.get("occurrence_count", 0)),
                repos or "—",
                format_timestamp(fp.get("last_seen")),
            )
        console.print(table)
    else:
        console.print("  [green]No failure patterns detected.[/green]")

    outliers = d.get("cost_outliers", [])
    if outliers:
        console.print()
        table = Table(title="Cost Outliers", show_edge=False)
        table.add_column("Execution", style="cyan", no_wrap=True)
        table.add_column("Repo")
        table.add_column("Cost", justify="right")
        table.add_column("vs Median", justify="right")
        for o in outliers:
            factor = o.get("deviation_factor", 0)
            table.add_row(
                o.get("execution_id", "")[:12],
                o.get("repo_full_name", ""),
                format_cost(o.get("cost_usd") or "0"),
                f"{factor:.1f}×",
            )
        console.print(table)


@app.command("history")
def system_history(
    system_id: Annotated[str, typer.Argument(help="System ID")],
    limit: Annotated[int, typer.Option(help="Max entries")] = 50,
    offset: Annotated[int, typer.Option(help="Pagination offset")] = 0,
) -> None:
    """Show full execution history for a system."""
    try:
        with get_client() as client:
            resp = client.get(
                f"/systems/{system_id}/history",
                params={"limit": limit, "offset": offset},
            )
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code == 404:
        print_error(f"System not found: {system_id}")
        raise typer.Exit(1)
    if resp.status_code != 200:
        print_error(resp.json().get("detail", f"HTTP {resp.status_code}"))
        raise typer.Exit(1)

    data = resp.json()
    entries = data.get("entries", [])
    if not entries:
        console.print("[dim]No history found.[/dim]")
        return

    table = Table(title=f"System History ({data.get('total', 0)} total)")
    table.add_column("Execution", style="cyan", no_wrap=True)
    table.add_column("Workflow")
    table.add_column("Status")
    table.add_column("Started")
    table.add_column("Completed")

    for e in entries:
        s = e.get("status", "")
        style = status_style(s)
        table.add_row(
            e.get("execution_id", "")[:12],
            e.get("workflow_name", ""),
            f"[{style}]{s}[/{style}]" if style else s,
            format_timestamp(e.get("started_at")),
            format_timestamp(e.get("completed_at")),
        )
    console.print(table)
