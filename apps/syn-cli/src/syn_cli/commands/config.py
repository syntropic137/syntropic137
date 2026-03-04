"""Configuration management commands — show, validate, env."""

from __future__ import annotations

import typer
from rich.table import Table

from syn_cli._output import console, print_error
from syn_cli.client import get_client

app = typer.Typer(
    name="config",
    help="Configuration management",
    no_args_is_help=True,
)


def _handle_connect_error() -> None:
    from syn_cli.client import get_api_url

    print_error(f"Could not connect to API at {get_api_url()}")
    console.print("[dim]Make sure the API server is running.[/dim]")
    raise typer.Exit(1)


@app.command("show")
def show_config(
    show_secrets: bool = typer.Option(False, "--show-secrets", help="Show secret values"),
) -> None:
    """Display current configuration."""
    try:
        with get_client() as client:
            resp = client.get("/config", params={"show_secrets": show_secrets})
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code != 200:
        print_error(resp.json().get("detail", f"HTTP {resp.status_code}"))
        raise typer.Exit(1)

    snapshot = resp.json()
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

    try:
        with get_client() as client:
            resp = client.get("/config/validate")
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code != 200:
        print_error(resp.json().get("detail", f"HTTP {resp.status_code}"))
        raise typer.Exit(1)

    issues = resp.json()
    if not isinstance(issues, list):
        issues = issues.get("issues", [])

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
    try:
        with get_client() as client:
            resp = client.get("/config/env")
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code != 200:
        print_error(resp.json().get("detail", f"HTTP {resp.status_code}"))
        raise typer.Exit(1)

    data = resp.json()
    template = data if isinstance(data, str) else data.get("template", str(data))
    console.print(template)
