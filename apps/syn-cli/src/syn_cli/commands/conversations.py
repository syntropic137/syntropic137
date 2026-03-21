"""Conversation log commands — show JSONL log lines and session metadata."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table

from syn_cli._output import console, format_timestamp, print_error
from syn_cli.client import get_client

app = typer.Typer(
    name="conversations",
    help="Inspect agent conversation logs",
    no_args_is_help=True,
)


def _handle_connect_error() -> None:
    from syn_cli.client import get_api_url

    print_error(f"Could not connect to API at {get_api_url()}")
    console.print("[dim]Make sure the API server is running.[/dim]")
    raise typer.Exit(1)


@app.command("show")
def show(
    session_id: Annotated[str, typer.Argument(help="Session ID")],
    offset: Annotated[int, typer.Option(help="Line offset for pagination")] = 0,
    limit: Annotated[int, typer.Option(help="Max lines to show (max 500)")] = 100,
) -> None:
    """Show parsed conversation log lines for a session."""
    try:
        with get_client() as client:
            resp = client.get(
                f"/conversations/{session_id}",
                params={"offset": offset, "limit": limit},
            )
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code == 404:
        print_error(f"Conversation not found: {session_id}")
        raise typer.Exit(1)
    if resp.status_code != 200:
        print_error(resp.json().get("detail", f"HTTP {resp.status_code}"))
        raise typer.Exit(1)

    data = resp.json()
    lines = data.get("lines", [])
    total = data.get("total_lines", 0)

    if not lines:
        console.print("[dim]No conversation lines found.[/dim]")
        return

    console.print(
        f"[bold]Conversation:[/bold] {session_id[:16]}  "
        f"[dim](lines {offset + 1}–{offset + len(lines)} of {total})[/dim]"
    )
    console.print()

    table = Table(show_edge=False, pad_edge=False)
    table.add_column("#", justify="right", style="dim", no_wrap=True)
    table.add_column("Type", style="cyan", no_wrap=True)
    table.add_column("Tool", style="dim", no_wrap=True)
    table.add_column("Preview")

    for line in lines:
        table.add_row(
            str(line.get("line_number", "")),
            line.get("event_type") or "—",
            line.get("tool_name") or "—",
            line.get("content_preview") or "—",
        )
    console.print(table)

    if total > offset + len(lines):
        next_offset = offset + limit
        console.print(f"[dim]More lines available. Use --offset {next_offset}.[/dim]")


@app.command("metadata")
def metadata(
    session_id: Annotated[str, typer.Argument(help="Session ID")],
) -> None:
    """Show metadata summary for a session's conversation."""
    try:
        with get_client() as client:
            resp = client.get(f"/conversations/{session_id}/metadata")
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code == 404:
        print_error(f"Conversation not found: {session_id}")
        raise typer.Exit(1)
    if resp.status_code != 200:
        print_error(resp.json().get("detail", f"HTTP {resp.status_code}"))
        raise typer.Exit(1)

    m = resp.json()
    if m is None:
        console.print("[dim]No metadata recorded for this session.[/dim]")
        return

    console.print(f"[bold]Metadata:[/bold] {m.get('session_id', session_id)}")
    if m.get("model"):
        console.print(f"  Model:         {m['model']}")
    if m.get("event_count") is not None:
        console.print(f"  Events:        {m['event_count']:,}")
    if m.get("total_input_tokens") is not None:
        console.print(f"  Input tokens:  {m['total_input_tokens']:,}")
    if m.get("total_output_tokens") is not None:
        console.print(f"  Output tokens: {m['total_output_tokens']:,}")
    if m.get("started_at"):
        console.print(f"  Started:       {format_timestamp(m['started_at'])}")
    if m.get("completed_at"):
        console.print(f"  Completed:     {format_timestamp(m['completed_at'])}")
    if m.get("size_bytes") is not None:
        console.print(f"  Log size:      {m['size_bytes']:,} bytes")
    if m.get("tool_counts"):
        console.print("  Tool counts:")
        for tool, count in sorted(m["tool_counts"].items(), key=lambda x: -x[1]):
            console.print(f"    {tool}: {count}")
