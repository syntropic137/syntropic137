"""Configuration management commands — show, validate, env."""

from __future__ import annotations

import typer
from rich.table import Table

from syn_api.types import Err, Ok
from syn_cli._async import run
from syn_cli._output import console

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
    import syn_api.v1.config as cfg

    result = run(cfg.get_config(show_secrets=show_secrets))

    match result:
        case Ok(snapshot):
            console.print("\n[bold]Application[/bold]")
            for k, v in snapshot.app.items():
                console.print(f"  {k}: {v}")

            console.print("\n[bold]Database[/bold]")
            for k, v in snapshot.database.items():
                console.print(f"  {k}: {v}")

            console.print("\n[bold]Agent Configuration[/bold]")
            for k, v in snapshot.agents.items():
                console.print(f"  {k}: {v}")

            console.print("\n[bold]Storage[/bold]")
            for k, v in snapshot.storage.items():
                console.print(f"  {k}: {v}")
        case Err(error, message=msg):
            console.print(f"[red]{msg or error}[/red]")
            raise typer.Exit(1)


@app.command("validate")
def validate_config() -> None:
    """Validate configuration and show issues."""
    import syn_api.v1.config as cfg

    console.print("Validating configuration...\n")

    result = run(cfg.validate_config())

    match result:
        case Ok(issues):
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
                table.add_row(
                    level_styles.get(issue.level, issue.level),
                    issue.category,
                    issue.message,
                )
                if issue.level == "error":
                    has_errors = True

            console.print(table)

            if has_errors:
                console.print("\n[red]Configuration has errors.[/red]")
                raise typer.Exit(1)
        case Err(error, message=msg):
            console.print(f"[red]{msg or error}[/red]")
            raise typer.Exit(1)


@app.command("env")
def show_env_template() -> None:
    """Show environment variable template."""
    import syn_api.v1.config as cfg

    result = run(cfg.get_env_template())

    match result:
        case Ok(template):
            console.print(template)
        case Err(error, message=msg):
            console.print(f"[red]{msg or error}[/red]")
            raise typer.Exit(1)
