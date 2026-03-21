"""Insights commands — global overview, cost summary, contribution heatmap."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table

from syn_cli._output import console, format_cost, format_tokens, print_error, status_style
from syn_cli.client import get_client

app = typer.Typer(
    name="insights",
    help="Global system insights and cost analysis",
    no_args_is_help=True,
)


def _handle_connect_error() -> None:
    from syn_cli.client import get_api_url

    print_error(f"Could not connect to API at {get_api_url()}")
    console.print("[dim]Make sure the API server is running.[/dim]")
    raise typer.Exit(1)


@app.command("overview")
def overview() -> None:
    """Show a global overview of all systems and their health."""
    try:
        with get_client() as client:
            resp = client.get("/insights/overview")
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code != 200:
        print_error(resp.json().get("detail", f"HTTP {resp.status_code}"))
        raise typer.Exit(1)

    d = resp.json()
    console.print(f"[bold]Global Overview[/bold]")
    console.print(f"  Systems:            {d.get('total_systems', 0)}")
    console.print(f"  Repos:              {d.get('total_repos', 0)}")
    if d.get("unassigned_repos"):
        console.print(f"  Unassigned repos:   [yellow]{d['unassigned_repos']}[/yellow]")
    console.print(f"  Active executions:  {d.get('total_active_executions', 0)}")
    console.print(f"  Total cost:         {format_cost(d.get('total_cost_usd') or '0')}")

    systems = d.get("systems", [])
    if systems:
        console.print()
        table = Table(title="Systems")
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("Name")
        table.add_column("Org")
        table.add_column("Repos", justify="right")
        table.add_column("Status")
        table.add_column("Active", justify="right")
        table.add_column("Cost", justify="right")

        for s in systems:
            st = s.get("overall_status", "")
            style = status_style(st)
            table.add_row(
                s.get("system_id", "")[:12],
                s.get("system_name", ""),
                s.get("organization_name", ""),
                str(s.get("repo_count", 0)),
                f"[{style}]{st}[/{style}]" if style else st,
                str(s.get("active_executions", 0)),
                format_cost(s.get("total_cost_usd") or "0"),
            )
        console.print(table)


@app.command("cost")
def cost() -> None:
    """Show global cost breakdown across repos, workflows, and models."""
    try:
        with get_client() as client:
            resp = client.get("/insights/cost")
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code != 200:
        print_error(resp.json().get("detail", f"HTTP {resp.status_code}"))
        raise typer.Exit(1)

    d = resp.json()
    console.print("[bold]Global Cost Summary[/bold]")
    console.print(f"  Total cost:      {format_cost(d.get('total_cost_usd') or '0')}")
    console.print(f"  Total tokens:    {format_tokens(d.get('total_tokens') or 0)}")
    console.print(f"    Input:         {format_tokens(d.get('total_input_tokens') or 0)}")
    console.print(f"    Output:        {format_tokens(d.get('total_output_tokens') or 0)}")
    console.print(f"  Executions:      {d.get('execution_count', 0)}")

    if d.get("cost_by_repo"):
        console.print()
        table = Table(title="Cost by Repo", show_edge=False)
        table.add_column("Repo", style="cyan")
        table.add_column("Cost", justify="right")
        for repo, c in sorted(d["cost_by_repo"].items(), key=lambda x: x[1], reverse=True)[:10]:
            table.add_row(repo, format_cost(c))
        console.print(table)

    if d.get("cost_by_model"):
        console.print()
        table = Table(title="Cost by Model", show_edge=False)
        table.add_column("Model", style="cyan")
        table.add_column("Cost", justify="right")
        for model, c in sorted(d["cost_by_model"].items(), key=lambda x: x[1], reverse=True):
            table.add_row(model, format_cost(c))
        console.print(table)


@app.command("heatmap")
def heatmap(
    org: Annotated[
        str | None, typer.Option("--org", help="Filter by organization ID")
    ] = None,
    system: Annotated[
        str | None, typer.Option("--system", help="Filter by system ID")
    ] = None,
    repo: Annotated[
        str | None, typer.Option("--repo", help="Filter by repo ID")
    ] = None,
    start: Annotated[
        str | None, typer.Option("--start", help="Start date (YYYY-MM-DD)")
    ] = None,
    end: Annotated[
        str | None, typer.Option("--end", help="End date (YYYY-MM-DD)")
    ] = None,
    metric: Annotated[
        str, typer.Option("--metric", "-m", help="Metric: sessions, cost, tokens")
    ] = "sessions",
) -> None:
    """Show a contribution heatmap of activity over time."""
    try:
        with get_client() as client:
            params: dict[str, str] = {"metric": metric}
            if org:
                params["organization_id"] = org
            if system:
                params["system_id"] = system
            if repo:
                params["repo_id"] = repo
            if start:
                params["start_date"] = start
            if end:
                params["end_date"] = end
            resp = client.get("/insights/contribution-heatmap", params=params)
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code == 400:
        print_error(resp.json().get("detail", "Invalid metric value."))
        raise typer.Exit(1)
    if resp.status_code != 200:
        print_error(resp.json().get("detail", f"HTTP {resp.status_code}"))
        raise typer.Exit(1)

    d = resp.json()
    console.print(
        f"[bold]Heatmap:[/bold] {d.get('metric', metric)}  "
        f"[dim]{d.get('start_date', '')} → {d.get('end_date', '')}[/dim]"
    )
    console.print(f"  Total: {d.get('total', 0)}")
    console.print()

    days = d.get("days", [])
    if not days:
        console.print("[dim]No data in this range.[/dim]")
        return

    # ASCII sparkline-style heatmap — one row, colour intensity by count
    max_count = max((day.get("count") or 0) for day in days) or 1
    blocks = " ░▒▓█"
    line = ""
    for day in days:
        count = day.get("count") or 0
        idx = min(int(count / max_count * (len(blocks) - 1)), len(blocks) - 1)
        line += blocks[idx]
    console.print(line)
    console.print(f"[dim]  {days[0].get('date', '')} … {days[-1].get('date', '')}[/dim]")

    # Top 5 days
    top = sorted(days, key=lambda x: x.get("count") or 0, reverse=True)[:5]
    if any(d.get("count") for d in top):
        console.print()
        table = Table(title="Top Days", show_edge=False)
        table.add_column("Date", style="cyan")
        table.add_column("Count", justify="right")
        for day in top:
            if day.get("count"):
                table.add_row(day.get("date", ""), str(day.get("count", 0)))
        console.print(table)
