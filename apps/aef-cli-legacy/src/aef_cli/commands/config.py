"""Configuration CLI commands.

Commands for validating and displaying configuration.
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from aef_adapters.agents import AgentProvider, get_available_agents
from aef_shared import get_settings
from aef_shared.logging import get_logger

logger = get_logger(__name__)
console = Console()

app = typer.Typer(
    name="config",
    help="Configuration management and validation",
)


@app.command("show")
def show_config(
    show_secrets: bool = typer.Option(
        False,
        "--show-secrets",
        help="Show secret values (use with caution)",
    ),
) -> None:
    """Display current configuration."""
    settings = get_settings()

    console.print(Panel.fit("[bold]Agentic Engineering Framework Configuration[/bold]"))
    console.print()

    # Application settings
    app_table = Table(title="Application")
    app_table.add_column("Setting", style="cyan")
    app_table.add_column("Value")

    app_table.add_row("App Name", settings.app_name)
    app_table.add_row("Environment", settings.app_environment.value)
    app_table.add_row("Debug Mode", str(settings.debug))
    app_table.add_row("Log Level", settings.log_level)
    app_table.add_row("Log Format", settings.log_format)

    console.print(app_table)
    console.print()

    # Database settings
    db_table = Table(title="Database")
    db_table.add_column("Setting", style="cyan")
    db_table.add_column("Value")

    if settings.aef_observability_db_url:
        # Mask password in URL
        db_url = str(settings.aef_observability_db_url)
        if not show_secrets and "@" in db_url:
            parts = db_url.split("@")
            masked = parts[0].rsplit(":", 1)[0] + ":****@" + parts[1]
            db_table.add_row("Observability DB", masked)
        else:
            db_table.add_row("Observability DB", db_url)
    else:
        db_table.add_row("Observability DB", "[yellow]Not configured[/yellow]")

    if settings.esp_event_store_db_url:
        # Mask password in URL
        db_url = str(settings.esp_event_store_db_url)
        if not show_secrets and "@" in db_url:
            parts = db_url.split("@")
            masked = parts[0].rsplit(":", 1)[0] + ":****@" + parts[1]
            db_table.add_row("ESP Event Store", masked)
        else:
            db_table.add_row("ESP Event Store", db_url)
    else:
        db_table.add_row("ESP Event Store", "[yellow]Not configured[/yellow]")

    db_table.add_row("Pool Size", str(settings.database_pool_size))
    db_table.add_row("Pool Overflow", str(settings.database_pool_overflow))

    console.print(db_table)
    console.print()

    # Agent settings
    agent_table = Table(title="Agent Configuration")
    agent_table.add_column("Setting", style="cyan")
    agent_table.add_column("Value")

    # Anthropic
    if settings.anthropic_api_key:
        if show_secrets:
            agent_table.add_row(
                "Anthropic API Key",
                settings.anthropic_api_key.get_secret_value(),
            )
        else:
            agent_table.add_row("Anthropic API Key", "[green]✓ Configured[/green]")
    else:
        agent_table.add_row("Anthropic API Key", "[yellow]Not set[/yellow]")

    # OpenAI
    if settings.openai_api_key:
        if show_secrets:
            agent_table.add_row(
                "OpenAI API Key",
                settings.openai_api_key.get_secret_value(),
            )
        else:
            agent_table.add_row("OpenAI API Key", "[green]✓ Configured[/green]")
    else:
        agent_table.add_row("OpenAI API Key", "[yellow]Not set[/yellow]")

    agent_table.add_row("Default Timeout", f"{settings.default_agent_timeout_seconds}s")
    agent_table.add_row("Default Max Tokens", str(settings.default_max_tokens))

    console.print(agent_table)
    console.print()

    # Storage settings
    storage_table = Table(title="Artifact Storage")
    storage_table.add_column("Setting", style="cyan")
    storage_table.add_column("Value")

    storage_table.add_row("Storage Type", settings.artifact_storage_type)

    if settings.artifact_storage_type == "s3":
        storage_table.add_row(
            "S3 Bucket",
            settings.s3_bucket_name or "[yellow]Not set[/yellow]",
        )
        storage_table.add_row(
            "S3 Endpoint",
            settings.s3_endpoint_url or "[dim]AWS S3[/dim]",
        )
        storage_table.add_row(
            "S3 Access Key",
            "[green]✓ Set[/green]" if settings.s3_access_key_id else "[yellow]Not set[/yellow]",
        )

    console.print(storage_table)


@app.command("validate")
def validate_config() -> None:
    """Validate configuration and show any issues."""
    console.print("[bold]Validating configuration...[/bold]")
    console.print()

    issues: list[str] = []
    warnings: list[str] = []

    try:
        settings = get_settings()
    except Exception as e:
        console.print(f"[red]✗ Configuration validation failed:[/red] {e}")
        raise typer.Exit(1) from None

    # Check database configuration
    if settings.aef_observability_db_url is None:
        if settings.is_test:
            warnings.append("No AEF_OBSERVABILITY_DB_URL - using in-memory storage (test mode)")
        else:
            warnings.append(
                "No AEF_OBSERVABILITY_DB_URL configured - run 'just dev' to start Docker PostgreSQL"
            )

    # Check agent configuration
    available_agents = get_available_agents()
    real_agents = [a for a in available_agents if a != AgentProvider.MOCK]

    if not real_agents:
        warnings.append("No AI agents configured - set ANTHROPIC_API_KEY or OPENAI_API_KEY")

    # Check production requirements
    if settings.is_production:
        if settings.aef_observability_db_url is None:
            issues.append("AEF_OBSERVABILITY_DB_URL is required in production")
        if settings.debug:
            issues.append("Debug mode should be disabled in production")
        if not real_agents:
            issues.append("At least one AI agent must be configured in production")

    # Display results
    if issues:
        console.print("[red]✗ Configuration has errors:[/red]")
        for issue in issues:
            console.print(f"  [red]•[/red] {issue}")
        console.print()

    if warnings:
        console.print("[yellow]⚠ Warnings:[/yellow]")
        for warning in warnings:
            console.print(f"  [yellow]•[/yellow] {warning}")
        console.print()

    if not issues and not warnings:
        console.print("[green]✓ Configuration is valid![/green]")
    elif not issues:
        console.print("[green]✓ Configuration is valid (with warnings)[/green]")
    else:
        raise typer.Exit(1)


@app.command("env")
def show_env_template() -> None:
    """Show environment variable template."""
    console.print("[bold]Environment Variables Template[/bold]")
    console.print()
    console.print("Copy these to your .env file and fill in the values:")
    console.print()

    template = """
# Application
APP_NAME=agentic-engineering-framework
APP_ENVIRONMENT=development
DEBUG=false
LOG_LEVEL=INFO
LOG_FORMAT=console

# Database (PostgreSQL)
# For local dev: just dev
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/aef

# Agent API Keys
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...

# Agent Defaults
DEFAULT_AGENT_TIMEOUT_SECONDS=300
DEFAULT_MAX_TOKENS=4096

# Artifact Storage (optional)
ARTIFACT_STORAGE_TYPE=database
# S3_BUCKET_NAME=
# S3_ENDPOINT_URL=
# S3_ACCESS_KEY_ID=
# S3_SECRET_ACCESS_KEY=
"""
    console.print(template)
    console.print()
    console.print("[dim]Or run: just gen-env[/dim]")
