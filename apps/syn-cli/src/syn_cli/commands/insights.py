"""Insights commands — global overview, cost summary, contribution heatmap."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table

from syn_cli._output import console, format_cost, format_tokens, status_style
from syn_cli.commands._api_helpers import api_get, build_params

app = typer.Typer(
    name="insights",
    help="Global system insights and cost analysis",
    no_args_is_help=True,
)


@app.command("overview")
def overview() -> None:
    """Show a global overview of all systems and their health."""
    d = api_get("/insights/overview")

    console.print("[bold]Global Overview[/bold]")
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
    d = api_get("/insights/cost")

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


def _render_heatmap(days: list[dict[str, object]], total: object) -> None:
    """Render sparkline and top-5 table for heatmap data."""
    console.print(f"  Total: {total}")
    console.print()

    def _count(day: dict[str, object]) -> int:
        c = day.get("count")
        return int(c) if isinstance(c, (int, float)) else 0

    max_count = max(_count(day) for day in days) or 1
    blocks = " ░▒▓█"
    line = ""
    for day in days:
        idx = min(int(_count(day) / max_count * (len(blocks) - 1)), len(blocks) - 1)
        line += blocks[idx]
    console.print(line)
    console.print(f"[dim]  {days[0].get('date', '')} … {days[-1].get('date', '')}[/dim]")

    top = sorted(days, key=_count, reverse=True)[:5]
    if any(_count(d) for d in top):
        console.print()
        table = Table(title="Top Days", show_edge=False)
        table.add_column("Date", style="cyan")
        table.add_column("Count", justify="right")
        for day in top:
            if _count(day):
                table.add_row(str(day.get("date", "")), str(_count(day)))
        console.print(table)


@app.command("heatmap")
def heatmap(
    org: Annotated[str | None, typer.Option("--org", help="Filter by organization ID")] = None,
    system: Annotated[str | None, typer.Option("--system", help="Filter by system ID")] = None,
    repo: Annotated[str | None, typer.Option("--repo", help="Filter by repo ID")] = None,
    start: Annotated[str | None, typer.Option("--start", help="Start date (YYYY-MM-DD)")] = None,
    end: Annotated[str | None, typer.Option("--end", help="End date (YYYY-MM-DD)")] = None,
    metric: Annotated[
        str, typer.Option("--metric", "-m", help="Metric: sessions, cost, tokens")
    ] = "sessions",
) -> None:
    """Show a contribution heatmap of activity over time."""
    if metric == "cost":
        metric = "cost_usd"

    params = build_params(
        metric=metric,
        organization_id=org,
        system_id=system,
        repo_id=repo,
        start_date=start,
        end_date=end,
    )
    d = api_get("/insights/contribution-heatmap", params=params)

    console.print(
        f"[bold]Heatmap:[/bold] {d.get('metric', metric)}  "
        f"[dim]{d.get('start_date', '')} → {d.get('end_date', '')}[/dim]"
    )

    days = d.get("days", [])
    if not days:
        console.print("[dim]No data in this range.[/dim]")
        return

    _render_heatmap(days, d.get("total", 0))
