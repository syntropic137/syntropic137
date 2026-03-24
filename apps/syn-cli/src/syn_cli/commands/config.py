"""Configuration management commands — show, validate, env."""

from __future__ import annotations

import typer
from rich.table import Table

from syn_cli._output import console
from syn_cli.commands._api_helpers import api_get

app = typer.Typer(
    name="config",
    help="Configuration management",
    no_args_is_help=True,
)


@app.command("show")
def show_config(
    show_secrets: bool = typer.Option(False, "--show-secrets", help="Show secret values"),
) -> None:
    """Display current configuration."""
    snapshot = api_get("/config", params={"show_secrets": show_secrets})

    console.print("\n[bold]Application[/bold]")
    for k, v in snapshot.get("app", {}).items():
        console.print(f"  {k}: {v}")

    console.print("\n[bold]Database[/bold]")
    for k, v in snapshot.get("database", {}).items():
        console.print(f"  {k}: {v}")

    console.print("\n[bold]Agent Configuration[/bold]")
    for k, v in snapshot.get("agents", {}).items():
        console.print(f"  {k}: {v}")

    console.print("\n[bold]Storage[/bold]")
    for k, v in snapshot.get("storage", {}).items():
        console.print(f"  {k}: {v}")


@app.command("validate")
def validate_config() -> None:
    """Validate configuration and show issues."""
    console.print("Validating configuration...\n")

    data = api_get("/config/validate")
    issues = data.get("issues", []) if isinstance(data, dict) else data

    if not issues:
        console.print("[green]No issues found.[/green]")
        return

    table = Table(title="Configuration Issues")
    table.add_column("Level")
    table.add_column("Category")
    table.add_column("Message")

    level_styles = {
        "error": "[red]error[/red]",
        "warning": "[yellow]warning[/yellow]",
        "info": "[blue]info[/blue]",
    }

    has_errors = False
    for issue in issues:
        level = issue.get("level", "info")
        table.add_row(
            level_styles.get(level, level),
            issue.get("category", ""),
            issue.get("message", ""),
        )
        if level == "error":
            has_errors = True

    console.print(table)

    if has_errors:
        console.print("\n[red]Configuration has errors.[/red]")
        raise typer.Exit(1)


@app.command("env")
def show_env_template() -> None:
    """Show environment variable template."""
    data = api_get("/config/env")
    template = data if isinstance(data, str) else data.get("template", str(data))
    console.print(template)
