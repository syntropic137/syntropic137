"""Artifact list, show, and content commands."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.syntax import Syntax
from rich.table import Table

from syn_cli._output import console, format_timestamp
from syn_cli.commands._api_helpers import api_get, api_get_list, build_params

app = typer.Typer(
    name="artifacts",
    help="Browse and retrieve workflow artifacts",
    no_args_is_help=True,
)


@app.command("list")
def list_artifacts(
    workflow: Annotated[
        str | None, typer.Option("--workflow", "-w", help="Filter by workflow ID")
    ] = None,
    phase: Annotated[str | None, typer.Option("--phase", "-p", help="Filter by phase ID")] = None,
    artifact_type: Annotated[
        str | None, typer.Option("--type", "-t", help="Filter by artifact type")
    ] = None,
    limit: Annotated[int, typer.Option(help="Max results (max 200)")] = 50,
) -> None:
    """List artifacts, optionally filtered by workflow or phase."""
    params = build_params(
        workflow_id=workflow,
        phase_id=phase,
        artifact_type=artifact_type,
        limit=limit,
    )
    items = api_get_list("/artifacts", params=params)

    if not items:
        console.print("[dim]No artifacts found.[/dim]")
        return

    table = Table(title="Artifacts")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Type")
    table.add_column("Title")
    table.add_column("Size", justify="right")
    table.add_column("Created")

    for a in items:
        size = a.get("size_bytes") or 0
        size_str = f"{size:,}B" if size < 1024 else f"{size // 1024}KB"
        table.add_row(
            a.get("id", "")[:12],
            a.get("artifact_type", ""),
            a.get("title") or "—",
            size_str,
            format_timestamp(a.get("created_at")),
        )
    console.print(table)


@app.command("show")
def show_artifact(
    artifact_id: Annotated[str, typer.Argument(help="Artifact ID")],
    no_content: Annotated[
        bool, typer.Option("--no-content", help="Skip content; show metadata only")
    ] = False,
) -> None:
    """Show artifact metadata and optionally its content."""
    a = api_get(f"/artifacts/{artifact_id}", params={"include_content": not no_content})

    console.print(f"[bold]Artifact:[/bold] {a.get('id', '')}")
    console.print(f"  Type:    {a.get('artifact_type', '')}")
    if a.get("title"):
        console.print(f"  Title:   {a['title']}")
    if a.get("workflow_id"):
        console.print(f"  Workflow: {a['workflow_id']}")
    if a.get("phase_id"):
        console.print(f"  Phase:   {a['phase_id']}")
    console.print(f"  Created: {format_timestamp(a.get('created_at'))}")
    size = a.get("size_bytes") or 0
    if size:
        console.print(f"  Size:    {size:,} bytes")

    if not no_content and a.get("content"):
        content_type = a.get("content_type", "text/plain")
        lexer = "markdown" if "markdown" in str(content_type) else "text"
        console.print()
        console.print(Syntax(a["content"], lexer, theme="github-dark", word_wrap=True))


@app.command("content")
def get_content(
    artifact_id: Annotated[str, typer.Argument(help="Artifact ID")],
    raw: Annotated[
        bool,
        typer.Option("--raw", help="Print raw content without syntax highlighting"),
    ] = False,
) -> None:
    """Print the raw content of an artifact."""
    data = api_get(f"/artifacts/{artifact_id}/content")

    content = data.get("content")
    if not content:
        console.print("[dim](no content)[/dim]")
        return

    if raw:
        print(content)
    else:
        content_type = data.get("content_type", "text/plain")
        lexer = "markdown" if "markdown" in str(content_type) else "text"
        console.print(Syntax(content, lexer, theme="github-dark", word_wrap=True))
