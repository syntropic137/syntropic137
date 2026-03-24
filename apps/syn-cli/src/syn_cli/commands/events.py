"""Event query commands — recent activity, session events, timeline, costs, tools."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table

from syn_cli._output import console, format_cost, format_duration, format_timestamp
from syn_cli.commands._api_helpers import api_get, api_get_list, build_params

app = typer.Typer(
    name="events",
    help="Query domain events and session observability",
    no_args_is_help=True,
)


@app.command("recent")
def recent(
    limit: Annotated[int, typer.Option(help="Max events to show (max 200)")] = 50,
) -> None:
    """Show recent domain events across all sessions."""
    data = api_get("/events/recent", params={"limit": limit})

    events = data.get("events", [])
    if not events:
        console.print("[dim]No recent events.[/dim]")
        return

    table = Table(title="Recent Events")
    table.add_column("Time")
    table.add_column("Type", style="cyan")
    table.add_column("Session", style="dim")
    table.add_column("Execution", style="dim")

    for ev in events:
        table.add_row(
            format_timestamp(str(ev.get("time", ""))),
            ev.get("event_type", ""),
            (ev.get("session_id") or "")[:12],
            (ev.get("execution_id") or "")[:12],
        )
    console.print(table)
    if data.get("has_more"):
        console.print("[dim]More events available. Use --limit to fetch more.[/dim]")


@app.command("session")
def session_events(
    session_id: Annotated[str, typer.Argument(help="Session ID")],
    event_type: Annotated[
        str | None, typer.Option("--type", "-t", help="Filter by event type")
    ] = None,
    limit: Annotated[int, typer.Option(help="Max events (max 1000)")] = 100,
    offset: Annotated[int, typer.Option(help="Pagination offset")] = 0,
) -> None:
    """List events for a specific session."""
    params = build_params(limit=limit, offset=offset, event_type=event_type)
    data = api_get(f"/events/sessions/{session_id}", params=params)

    events = data.get("events", [])
    if not events:
        console.print(f"[dim]No events for session {session_id}.[/dim]")
        return

    table = Table(title=f"Events: {session_id[:12]}")
    table.add_column("Time")
    table.add_column("Type", style="cyan")
    table.add_column("Phase", style="dim")

    for ev in events:
        table.add_row(
            format_timestamp(str(ev.get("time", ""))),
            ev.get("event_type", ""),
            (ev.get("phase_id") or "")[:12],
        )
    console.print(table)
    if data.get("has_more"):
        console.print(f"[dim]More events available. Use --offset {offset + limit}.[/dim]")


@app.command("timeline")
def timeline(
    session_id: Annotated[str, typer.Argument(help="Session ID")],
    limit: Annotated[int, typer.Option(help="Max entries (max 500)")] = 100,
) -> None:
    """Show a chronological tool-call timeline for a session."""
    entries = api_get_list(f"/events/sessions/{session_id}/timeline", params={"limit": limit})

    if not entries:
        console.print("[dim]No timeline entries.[/dim]")
        return

    table = Table(title=f"Timeline: {session_id[:12]}")
    table.add_column("Time")
    table.add_column("Event", style="cyan")
    table.add_column("Tool")
    table.add_column("Duration", justify="right")
    table.add_column("✓")

    for e in entries:
        dur = e.get("duration_ms")
        success = e.get("success")
        table.add_row(
            format_timestamp(str(e.get("time", ""))),
            e.get("event_type", ""),
            e.get("tool_name") or "—",
            format_duration(dur) if dur is not None else "—",
            "[green]✓[/green]" if success else ("[red]✗[/red]" if success is False else "—"),
        )
    console.print(table)


@app.command("costs")
def session_costs(
    session_id: Annotated[str, typer.Argument(help="Session ID")],
) -> None:
    """Show token usage and cost breakdown for a session."""
    d = api_get(f"/events/sessions/{session_id}/costs")

    console.print(f"[bold]Session costs:[/bold] {d.get('session_id', session_id)}")
    console.print(f"  Input tokens:       {d.get('input_tokens', 0):,}")
    console.print(f"  Output tokens:      {d.get('output_tokens', 0):,}")
    console.print(f"  Total tokens:       {d.get('total_tokens', 0):,}")
    if d.get("cache_creation_tokens"):
        console.print(f"  Cache creation:     {d['cache_creation_tokens']:,}")
    if d.get("cache_read_tokens"):
        console.print(f"  Cache read:         {d['cache_read_tokens']:,}")
    if d.get("estimated_cost_usd") is not None:
        console.print(f"  Estimated cost:     {format_cost(d['estimated_cost_usd'])}")


@app.command("tools")
def session_tools(
    session_id: Annotated[str, typer.Argument(help="Session ID")],
) -> None:
    """Show tool usage summary for a session."""
    tools = api_get_list(f"/events/sessions/{session_id}/tools")

    if not tools:
        console.print("[dim]No tool usage recorded.[/dim]")
        return

    table = Table(title=f"Tool Usage: {session_id[:12]}")
    table.add_column("Tool", style="cyan")
    table.add_column("Calls", justify="right")
    table.add_column("Success", justify="right")
    table.add_column("Errors", justify="right")
    table.add_column("Avg Duration", justify="right")

    for t in sorted(tools, key=lambda x: x.get("call_count", 0), reverse=True):
        avg_ms = t.get("avg_duration_ms")
        table.add_row(
            t.get("tool_name", ""),
            str(t.get("call_count", 0)),
            str(t.get("success_count", 0)),
            str(t.get("error_count", 0)),
            format_duration(avg_ms) if avg_ms else "—",
        )
    console.print(table)
