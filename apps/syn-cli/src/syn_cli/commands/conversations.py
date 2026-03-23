"""Conversation log commands — show JSONL log lines and session metadata."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table

from syn_cli._output import console, format_timestamp
from syn_cli.commands._api_helpers import api_get

app = typer.Typer(
    name="conversations",
    help="Inspect agent conversation logs",
    no_args_is_help=True,
)


@app.command("show")
def show(
    session_id: Annotated[str, typer.Argument(help="Session ID")],
    offset: Annotated[int, typer.Option(help="Line offset for pagination")] = 0,
    limit: Annotated[int, typer.Option(help="Max lines to show (max 500)")] = 100,
) -> None:
    """Show parsed conversation log lines for a session."""
    data = api_get(
        f"/conversations/{session_id}",
        params={"offset": offset, "limit": limit},
    )

    lines = data.get("lines", [])
    total = data.get("total_lines", 0)

    if not lines:
        console.print("[dim]No conversation lines found.[/dim]")
        return

    console.print(
        f"[bold]Conversation:[/bold] {session_id[:16]}  "
        f"[dim](lines {offset + 1}-{offset + len(lines)} of {total})[/dim]"
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


def _format_field(value: object, fmt: str) -> str:
    """Format a metadata field value by format type."""
    if fmt == "ts":
        return format_timestamp(str(value))
    if fmt == "bytes":
        return f"{value:,} bytes"
    if fmt == ":,":
        return f"{value:,}"
    return str(value)


_METADATA_FIELDS: list[tuple[str, str, str]] = [
    ("model", "Model", ""),
    ("event_count", "Events", ":,"),
    ("total_input_tokens", "Input tokens", ":,"),
    ("total_output_tokens", "Output tokens", ":,"),
    ("started_at", "Started", "ts"),
    ("completed_at", "Completed", "ts"),
    ("size_bytes", "Log size", "bytes"),
]


@app.command("metadata")
def metadata(
    session_id: Annotated[str, typer.Argument(help="Session ID")],
) -> None:
    """Show metadata summary for a session's conversation."""
    m = api_get(f"/conversations/{session_id}/metadata")

    if m is None:
        console.print("[dim]No metadata recorded for this session.[/dim]")
        return

    console.print(f"[bold]Metadata:[/bold] {m.get('session_id', session_id)}")
    for key, label, fmt in _METADATA_FIELDS:
        value = m.get(key)
        if value is None:
            continue
        console.print(f"  {label + ':':17s}{_format_field(value, fmt)}")

    if m.get("tool_counts"):
        console.print("  Tool counts:")
        for tool, count in sorted(m["tool_counts"].items(), key=lambda x: -x[1]):
            console.print(f"    {tool}: {count}")
