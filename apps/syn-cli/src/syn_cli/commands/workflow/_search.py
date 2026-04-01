"""Workflow marketplace discovery — search and info commands."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

import typer
from rich.panel import Panel
from rich.table import Table

from syn_cli._output import console, print_error
from syn_cli.commands._marketplace_client import (
    resolve_plugin_by_name,
    search_all_registries,
)
from syn_cli.commands.workflow._crud import app

if TYPE_CHECKING:
    from syn_cli.commands._marketplace_models import MarketplacePluginEntry


def _print_no_results(query: str, category: str | None, tag: str | None) -> None:
    """Print empty results message with contextual help."""
    console.print("[dim]No workflows found.[/dim]")
    if not query and not category and not tag:
        console.print(
            "[dim]Add a marketplace first: syn marketplace add syntropic137/workflow-library[/dim]"
        )


def _print_search_results(
    results: list[tuple[str, MarketplacePluginEntry]],
) -> None:
    """Print search results as a table."""
    table = Table(title="Available Workflows")
    table.add_column("Name", style="bold")
    table.add_column("Version")
    table.add_column("Category")
    table.add_column("Description")
    table.add_column("Registry", style="dim")

    for reg_name, plugin in results:
        table.add_row(
            plugin.name,
            plugin.version,
            plugin.category or "-",
            _truncate(plugin.description, 50),
            reg_name,
        )

    console.print(table)
    console.print(
        f"\n[dim]{len(results)} result{'s' if len(results) != 1 else ''}. "
        f"Install with: syn workflow install <name>[/dim]"
    )


@app.command("search")
def search_workflows(
    query: Annotated[
        str,
        typer.Argument(help="Search term (matches name, description, tags)"),
    ] = "",
    category: Annotated[
        str | None,
        typer.Option("--category", "-c", help="Filter by category"),
    ] = None,
    tag: Annotated[
        str | None,
        typer.Option("--tag", "-t", help="Filter by tag"),
    ] = None,
    registry: Annotated[
        str | None,
        typer.Option("--registry", "-r", help="Search specific marketplace only"),
    ] = None,
) -> None:
    """Search for workflows across registered marketplaces."""
    results = search_all_registries(query, category=category, tag=tag)

    if registry:
        results = [(rn, p) for rn, p in results if rn == registry]

    if not results:
        _print_no_results(query, category, tag)
        return

    _print_search_results(results)


@app.command("info")
def workflow_info(
    name: Annotated[
        str,
        typer.Argument(help="Plugin name from marketplace"),
    ],
) -> None:
    """Show details of a marketplace workflow plugin."""
    result = resolve_plugin_by_name(name)

    if result is None:
        print_error(f"Plugin '{name}' not found in any registered marketplace")
        console.print("[dim]Try: syn workflow search[/dim]")
        raise typer.Exit(1)

    reg_name, entry, plugin = result

    tags_str = ", ".join(plugin.tags) if plugin.tags else "-"
    info = (
        f"[bold]Name:[/bold]        {plugin.name}\n"
        f"[bold]Version:[/bold]     {plugin.version}\n"
        f"[bold]Description:[/bold] {plugin.description or '-'}\n"
        f"[bold]Category:[/bold]    {plugin.category or '-'}\n"
        f"[bold]Tags:[/bold]        {tags_str}\n"
        f"[bold]Source:[/bold]      {entry.repo} ({plugin.source})\n"
        f"[bold]Registry:[/bold]    {reg_name}\n"
        f"\n[dim]Install: syn workflow install {plugin.name}[/dim]"
    )

    console.print(Panel(info, title=f"[bold]{plugin.name}[/bold]", expand=False))


def _truncate(text: str, max_len: int) -> str:
    """Truncate text with ellipsis if needed."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."
