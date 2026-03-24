"""System observability commands — status, cost, activity, patterns, history."""

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
    status_style,
)
from syn_cli.commands._api_helpers import api_get
from syn_cli.commands.system._crud import app


def _render_repo_health_table(repos: list[dict[str, object]]) -> None:
    """Render repo health sub-table for system status."""
    table = Table(title="Repo Health", show_edge=False)
    table.add_column("Repo", style="cyan")
    table.add_column("Status")
    table.add_column("Success Rate", justify="right")
    table.add_column("Active", justify="right")
    table.add_column("Last Run")
    for r in repos:
        rate = r.get("success_rate")
        table.add_row(
            str(r.get("repo_full_name", "")),
            format_status(str(r.get("status", ""))),
            f"{rate:.0%}" if rate is not None else "—",
            str(r.get("active_executions", 0)),
            format_timestamp(r.get("last_execution_at")),  # type: ignore[arg-type]
        )
    console.print(table)


@app.command("status")
def system_status(
    system_id: Annotated[str, typer.Argument(help="System ID")],
) -> None:
    """Show health status of a system and its repos."""
    d = api_get(f"/systems/{system_id}/status")

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
        _render_repo_health_table(repos)


@app.command("cost")
def system_cost(
    system_id: Annotated[str, typer.Argument(help="System ID")],
) -> None:
    """Show cost breakdown for a system."""
    d = api_get(f"/systems/{system_id}/cost")

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


def _render_execution_table(
    entries: list[dict[str, object]], title: str, *, show_completed: bool = False
) -> None:
    """Render an execution entries table (shared by activity/history)."""
    table = Table(title=title)
    table.add_column("Execution", style="cyan", no_wrap=True)
    table.add_column("Workflow")
    table.add_column("Status")
    table.add_column("Started")
    if show_completed:
        table.add_column("Completed")
    else:
        table.add_column("Trigger")

    for e in entries:
        row = [
            str(e.get("execution_id", ""))[:12],
            str(e.get("workflow_name", "")),
            format_status(str(e.get("status", ""))),
            format_timestamp(e.get("started_at")),  # type: ignore[arg-type]
        ]
        row.append(
            format_timestamp(e.get("completed_at"))  # type: ignore[arg-type]
            if show_completed
            else str(e.get("trigger_source") or "—")
        )
        table.add_row(*row)
    console.print(table)


@app.command("activity")
def system_activity(
    system_id: Annotated[str, typer.Argument(help="System ID")],
    limit: Annotated[int, typer.Option(help="Max entries")] = 50,
    offset: Annotated[int, typer.Option(help="Pagination offset")] = 0,
) -> None:
    """Show recent execution activity for a system."""
    data = api_get(
        f"/systems/{system_id}/activity",
        params={"limit": limit, "offset": offset},
    )

    entries = data.get("entries", [])
    if not entries:
        console.print("[dim]No activity found.[/dim]")
        return

    _render_execution_table(entries, f"System Activity ({data.get('total', 0)} total)")


def _render_failure_patterns(failures: list[dict[str, object]]) -> None:
    """Render failure patterns table."""
    table = Table(title="Failure Patterns", show_edge=False)
    table.add_column("Error Type", style="red")
    table.add_column("Count", justify="right")
    table.add_column("Affected Repos")
    table.add_column("Last Seen")
    for fp in failures:
        repos = ", ".join(fp.get("affected_repos", []))  # type: ignore[arg-type]
        table.add_row(
            str(fp.get("error_type", "")),
            str(fp.get("occurrence_count", 0)),
            repos or "—",
            format_timestamp(fp.get("last_seen")),  # type: ignore[arg-type]
        )
    console.print(table)


def _render_cost_outliers(outliers: list[dict[str, object]]) -> None:
    """Render cost outliers table."""
    table = Table(title="Cost Outliers", show_edge=False)
    table.add_column("Execution", style="cyan", no_wrap=True)
    table.add_column("Repo")
    table.add_column("Cost", justify="right")
    table.add_column("vs Median", justify="right")
    for o in outliers:
        factor = o.get("deviation_factor", 0)
        table.add_row(
            str(o.get("execution_id", ""))[:12],
            str(o.get("repo_full_name", "")),
            format_cost(str(o.get("cost_usd") or "0")),
            f"{factor:.1f}x",
        )
    console.print(table)


@app.command("patterns")
def system_patterns(
    system_id: Annotated[str, typer.Argument(help="System ID")],
) -> None:
    """Show failure patterns and cost outliers for a system."""
    d = api_get(f"/systems/{system_id}/patterns")

    console.print(
        f"[bold]{d.get('system_name', system_id)} — Patterns[/bold]  "
        f"[dim](last {d.get('analysis_window_hours', 168)}h)[/dim]"
    )

    failures = d.get("failure_patterns", [])
    if failures:
        console.print()
        _render_failure_patterns(failures)
    else:
        console.print("  [green]No failure patterns detected.[/green]")

    outliers = d.get("cost_outliers", [])
    if outliers:
        console.print()
        _render_cost_outliers(outliers)


@app.command("history")
def system_history(
    system_id: Annotated[str, typer.Argument(help="System ID")],
    limit: Annotated[int, typer.Option(help="Max entries")] = 50,
    offset: Annotated[int, typer.Option(help="Pagination offset")] = 0,
) -> None:
    """Show full execution history for a system."""
    data = api_get(
        f"/systems/{system_id}/history",
        params={"limit": limit, "offset": offset},
    )

    entries = data.get("entries", [])
    if not entries:
        console.print("[dim]No history found.[/dim]")
        return

    _render_execution_table(
        entries, f"System History ({data.get('total', 0)} total)", show_completed=True
    )
