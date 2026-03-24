"""Repository management commands — register, list, show, assign, and observability."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table

from syn_cli._output import (
    console,
    format_cost,
    format_status,
    format_timestamp,
    format_tokens,
)
from syn_cli.commands._api_helpers import api_get, api_post, build_params

app = typer.Typer(
    name="repo",
    help="Manage repositories and their observability",
    no_args_is_help=True,
)


@app.command("register")
def register(
    org: Annotated[str, typer.Option("--org", "-o", help="Organization ID")],
    url: Annotated[str, typer.Option("--url", "-u", help="Full repo name (owner/repo)")],
    system: Annotated[
        str | None, typer.Option("--system", "-s", help="Assign to system immediately")
    ] = None,
    provider: Annotated[str, typer.Option(help="Provider (github, gitlab, …)")] = "github",
    branch: Annotated[str, typer.Option(help="Default branch")] = "main",
    private: Annotated[bool, typer.Option("--private/--public", help="Private repo")] = False,
    created_by: Annotated[str, typer.Option(help="Creator identifier")] = "cli",
) -> None:
    """Register a repository with an organization."""
    data = api_post(
        "/repos",
        json={
            "organization_id": org,
            "full_name": url,
            "provider": provider,
            "default_branch": branch,
            "is_private": private,
            "created_by": created_by,
        },
    )

    repo_id = data.get("repo_id", "")
    console.print(f"[green]Repo registered:[/green] {repo_id}")
    console.print(f"  Full name: {url}")

    if system:
        try:
            api_post(f"/repos/{repo_id}/assign", json={"system_id": system})
            console.print(f"  [green]Assigned to system:[/green] {system}")
        except (typer.Exit, Exception):
            console.print("  [yellow]Could not assign to system.[/yellow]")


@app.command("list")
def list_repos(
    org: Annotated[
        str | None, typer.Option("--org", "-o", help="Filter by organization ID")
    ] = None,
    system: Annotated[
        str | None, typer.Option("--system", "-s", help="Filter by system ID")
    ] = None,
    unassigned: Annotated[
        bool, typer.Option("--unassigned", help="Only repos without a system")
    ] = False,
) -> None:
    """List registered repositories."""
    params = build_params(organization_id=org, system_id=system)
    if unassigned:
        params["unassigned"] = True
    data = api_get("/repos", params=params)

    repos = data.get("repos", [])
    if not repos:
        console.print("[dim]No repos found.[/dim]")
        return

    table = Table(title=f"Repos ({data.get('total', len(repos))})")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Repo")
    table.add_column("Provider")
    table.add_column("Branch")
    table.add_column("System")
    table.add_column("Created")

    for r in repos:
        table.add_row(
            r.get("repo_id", "")[:12],
            r.get("full_name", ""),
            r.get("provider", ""),
            r.get("default_branch", ""),
            r.get("system_id") or "[dim]—[/dim]",
            format_timestamp(str(r.get("created_at") or "")),
        )
    console.print(table)


@app.command("show")
def show(
    repo_id: Annotated[str, typer.Argument(help="Repo ID")],
) -> None:
    """Show repo details."""
    r = api_get(f"/repos/{repo_id}")

    console.print(f"[bold]Repo:[/bold] {r.get('full_name', '')}")
    console.print(f"  ID:           {r.get('repo_id', '')}")
    console.print(f"  Provider:     {r.get('provider', '')}")
    console.print(f"  Branch:       {r.get('default_branch', '')}")
    console.print(f"  Organization: {r.get('organization_id', '')}")
    if r.get("system_id"):
        console.print(f"  System:       {r['system_id']}")
    console.print(f"  Private:      {'yes' if r.get('is_private') else 'no'}")
    console.print(f"  Created:      {format_timestamp(str(r.get('created_at') or ''))}")


@app.command("assign")
def assign(
    repo_id: Annotated[str, typer.Argument(help="Repo ID")],
    system: Annotated[str, typer.Option("--system", "-s", help="System ID")],
) -> None:
    """Assign a repo to a system."""
    api_post(f"/repos/{repo_id}/assign", json={"system_id": system})
    console.print(f"[green]Repo assigned:[/green] {repo_id} → system {system}")


@app.command("unassign")
def unassign(
    repo_id: Annotated[str, typer.Argument(help="Repo ID")],
) -> None:
    """Remove a repo from its system."""
    api_post(f"/repos/{repo_id}/unassign")
    console.print(f"[yellow]Repo unassigned:[/yellow] {repo_id}")


@app.command("health")
def repo_health(
    repo_id: Annotated[str, typer.Argument(help="Repo ID")],
) -> None:
    """Show health metrics for a repo."""
    d = api_get(f"/repos/{repo_id}/health")

    trend = d.get("trend", "")
    trend_icon = {"improving": "↑", "degrading": "↓", "stable": "→"}.get(str(trend), "")

    console.print(f"[bold]{d.get('repo_full_name', repo_id)} — Health[/bold]")
    console.print(f"  Executions:   {d.get('total_executions', 0)}")
    console.print(f"  Successful:   {d.get('successful_executions', 0)}")
    console.print(f"  Failed:       {d.get('failed_executions', 0)}")
    rate = d.get("success_rate")
    if rate is not None:
        console.print(f"  Success rate: {rate:.0%}")
    console.print(f"  Trend:        {trend_icon} {trend}")
    console.print(f"  Cost (window):{format_cost(d.get('window_cost_usd') or '0')}")
    console.print(f"  Last run:     {format_timestamp(d.get('last_execution_at'))}")


@app.command("cost")
def repo_cost(
    repo_id: Annotated[str, typer.Argument(help="Repo ID")],
) -> None:
    """Show cost breakdown for a repo."""
    d = api_get(f"/repos/{repo_id}/cost")

    console.print(f"[bold]{d.get('repo_full_name', repo_id)} — Cost[/bold]")
    console.print(f"  Total cost:    {format_cost(d.get('total_cost_usd') or '0')}")
    console.print(f"  Total tokens:  {format_tokens(d.get('total_tokens') or 0)}")
    console.print(f"  Executions:    {d.get('execution_count', 0)}")

    if d.get("cost_by_model"):
        console.print()
        table = Table(title="By Model", show_edge=False)
        table.add_column("Model", style="cyan")
        table.add_column("Cost", justify="right")
        for model, c in sorted(d["cost_by_model"].items(), key=lambda x: x[1], reverse=True):
            table.add_row(model, format_cost(c))
        console.print(table)


@app.command("activity")
def repo_activity(
    repo_id: Annotated[str, typer.Argument(help="Repo ID")],
    limit: Annotated[int, typer.Option(help="Max entries")] = 50,
    offset: Annotated[int, typer.Option(help="Pagination offset")] = 0,
) -> None:
    """Show recent execution activity for a repo."""
    data = api_get(f"/repos/{repo_id}/activity", params={"limit": limit, "offset": offset})

    entries = data.get("entries", [])
    if not entries:
        console.print("[dim]No activity found.[/dim]")
        return

    table = Table(title=f"Repo Activity ({data.get('total', 0)} total)")
    table.add_column("Execution", style="cyan", no_wrap=True)
    table.add_column("Workflow")
    table.add_column("Status")
    table.add_column("Started")
    table.add_column("Trigger")

    for e in entries:
        table.add_row(
            e.get("execution_id", "")[:12],
            e.get("workflow_name", ""),
            format_status(e.get("status", "")),
            format_timestamp(e.get("started_at")),
            e.get("trigger_source") or "—",
        )
    console.print(table)


@app.command("failures")
def repo_failures(
    repo_id: Annotated[str, typer.Argument(help="Repo ID")],
    limit: Annotated[int, typer.Option(help="Max failures to show")] = 50,
) -> None:
    """Show recent execution failures for a repo."""
    data = api_get(f"/repos/{repo_id}/failures", params={"limit": limit})

    failures = data.get("failures", [])
    if not failures:
        console.print("[green]No failures found.[/green]")
        return

    table = Table(title=f"Failures ({data.get('total', len(failures))} total)")
    table.add_column("Execution", style="cyan", no_wrap=True)
    table.add_column("Workflow")
    table.add_column("Phase")
    table.add_column("Failed At")
    table.add_column("Error")

    for f in failures:
        table.add_row(
            f.get("execution_id", "")[:12],
            f.get("workflow_name", ""),
            f.get("phase_name") or "—",
            format_timestamp(f.get("failed_at")),
            (f.get("error_message") or "")[:60],
        )
    console.print(table)


@app.command("sessions")
def repo_sessions(
    repo_id: Annotated[str, typer.Argument(help="Repo ID")],
    limit: Annotated[int, typer.Option(help="Max sessions to show")] = 50,
) -> None:
    """Show agent sessions associated with a repo."""
    data = api_get(f"/repos/{repo_id}/sessions", params={"limit": limit})

    sessions = data.get("sessions", [])
    if not sessions:
        console.print("[dim]No sessions found.[/dim]")
        return

    table = Table(title=f"Sessions ({data.get('total', len(sessions))} total)")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Execution", no_wrap=True)
    table.add_column("Status")
    table.add_column("Started")
    table.add_column("Tokens", justify="right")
    table.add_column("Cost", justify="right")

    for s in sessions:
        table.add_row(
            s.get("id", "")[:12],
            s.get("execution_id", "")[:12],
            format_status(s.get("status", "")),
            format_timestamp(s.get("started_at")),
            format_tokens(s.get("total_tokens") or 0),
            format_cost(s.get("total_cost_usd") or "0"),
        )
    console.print(table)
