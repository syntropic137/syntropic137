"""Marketplace registry management — add, list, remove, refresh."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table

from syn_cli._output import console, format_timestamp, print_error, print_success
from syn_cli.commands._marketplace_client import (
    fetch_marketplace_json,
    load_registries,
    refresh_index,
    save_cached_index,
    save_registries,
)
from syn_cli.commands._marketplace_models import (
    CachedMarketplace,
    RegistryConfig,
    RegistryEntry,
)

app = typer.Typer(
    name="marketplace",
    help="Manage workflow marketplace registries.",
    no_args_is_help=True,
)


@app.command("add")
def add_marketplace(
    repo: Annotated[
        str,
        typer.Argument(help="GitHub repo (org/repo shorthand)"),
    ],
    ref: Annotated[
        str,
        typer.Option("--ref", "-r", help="Git branch or tag"),
    ] = "main",
    name: Annotated[
        str | None,
        typer.Option("--name", "-n", help="Override registry name"),
    ] = None,
) -> None:
    """Register a GitHub repo as a workflow marketplace."""
    console.print(f"Fetching marketplace.json from [cyan]{repo}[/cyan]@{ref}...")

    try:
        index = fetch_marketplace_json(repo, ref)
    except RuntimeError as e:
        print_error(str(e))
        raise typer.Exit(1) from None

    registry_name = name or index.name

    config = load_registries()
    if registry_name in config.registries:
        print_error(f"Marketplace '{registry_name}' is already registered")
        console.print("[dim]Use 'syn marketplace remove' first to re-register.[/dim]")
        raise typer.Exit(1)

    from datetime import UTC, datetime

    entry = RegistryEntry(
        repo=repo,
        ref=ref,
        added_at=datetime.now(tz=UTC).isoformat(),
    )
    updated = RegistryConfig(
        version=config.version,
        registries={**config.registries, registry_name: entry},
    )
    save_registries(updated)

    # Cache the index we just fetched
    save_cached_index(
        registry_name,
        CachedMarketplace(
            fetched_at=datetime.now(tz=UTC).isoformat(),
            index=index,
        ),
    )

    plugin_count = len(index.plugins)
    print_success(
        f"Added marketplace [bold]{registry_name}[/bold] "
        f"({plugin_count} plugin{'s' if plugin_count != 1 else ''})"
    )


@app.command("list")
def list_marketplaces() -> None:
    """List registered marketplace registries."""
    config = load_registries()

    if not config.registries:
        console.print("[dim]No marketplaces registered.[/dim]")
        console.print(
            "[dim]Add one with: syn marketplace add syntropic137/workflow-library[/dim]"
        )
        return

    table = Table(title="Registered Marketplaces")
    table.add_column("Name", style="bold")
    table.add_column("Repo")
    table.add_column("Ref")
    table.add_column("Added")

    for name, entry in config.registries.items():
        table.add_row(
            name,
            entry.repo,
            entry.ref,
            format_timestamp(entry.added_at),
        )

    console.print(table)


@app.command("remove")
def remove_marketplace(
    name: Annotated[
        str,
        typer.Argument(help="Registry name to remove"),
    ],
) -> None:
    """Remove a registered marketplace."""
    config = load_registries()

    if name not in config.registries:
        print_error(f"Marketplace '{name}' is not registered")
        raise typer.Exit(1)

    remaining = {k: v for k, v in config.registries.items() if k != name}
    updated = RegistryConfig(version=config.version, registries=remaining)
    save_registries(updated)

    # Clean up cache
    from syn_cli.commands._marketplace_client import _CACHE_DIR

    cache_path = _CACHE_DIR / f"{name}.json"
    if cache_path.exists():
        cache_path.unlink()

    print_success(f"Removed marketplace [bold]{name}[/bold]")


@app.command("refresh")
def refresh_marketplace(
    name: Annotated[
        str | None,
        typer.Argument(help="Registry name (refreshes all if omitted)"),
    ] = None,
) -> None:
    """Force-refresh cached marketplace indexes."""
    config = load_registries()

    if not config.registries:
        console.print("[dim]No marketplaces registered.[/dim]")
        return

    targets: list[tuple[str, RegistryEntry]]
    if name:
        if name not in config.registries:
            print_error(f"Marketplace '{name}' is not registered")
            raise typer.Exit(1)
        targets = [(name, config.registries[name])]
    else:
        targets = list(config.registries.items())

    for reg_name, entry in targets:
        console.print(f"Refreshing [cyan]{reg_name}[/cyan]...", end=" ")
        try:
            index = refresh_index(reg_name, entry, force=True)
            plugin_count = len(index.plugins)
            console.print(
                f"[green]done[/green] "
                f"({plugin_count} plugin{'s' if plugin_count != 1 else ''})"
            )
        except RuntimeError as e:
            console.print(f"[red]failed[/red] ({e})")
