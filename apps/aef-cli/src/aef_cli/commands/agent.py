"""Agent CLI commands.

Commands for interacting with AI agent providers.
"""

from __future__ import annotations

import asyncio

import typer
from rich.console import Console
from rich.table import Table

from aef_adapters.agents import (
    AgentConfig,
    AgentError,
    AgentMessage,
    AgentProvider,
    get_agent,
    get_available_agents,
)
from aef_shared.logging import get_logger

logger = get_logger(__name__)
console = Console()

app = typer.Typer(
    name="agent",
    help="AI agent management and interaction",
)


@app.command("list")
def list_agents() -> None:
    """List available agent providers."""
    available = get_available_agents()

    table = Table(title="Available Agents")
    table.add_column("Provider", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Default Model")

    # Check each provider
    for provider in AgentProvider:
        if provider == AgentProvider.MOCK:
            continue  # Skip mock in user-facing list

        is_available = provider in available
        status = "[green]✓ Available[/green]" if is_available else "[red]✗ Not configured[/red]"

        model = ""
        if provider == AgentProvider.CLAUDE:
            model = "claude-sonnet-4-20250514"
        elif provider == AgentProvider.OPENAI:
            model = "gpt-4o"

        table.add_row(provider.value, status, model)

    console.print(table)

    if not available or (len(available) == 1 and AgentProvider.MOCK in available):
        console.print()
        console.print("[yellow]No agents configured![/yellow]")
        console.print("Set ANTHROPIC_API_KEY or OPENAI_API_KEY in your environment.")


@app.command("test")
def test_agent(
    provider: str = typer.Option(
        None,
        "--provider",
        "-p",
        help="Provider to test (claude, openai). Auto-selects if not specified.",
    ),
    prompt: str = typer.Option(
        "Say 'Hello from AEF!' in exactly 5 words.",
        "--prompt",
        help="Test prompt to send",
    ),
    model: str = typer.Option(None, "--model", "-m", help="Model to use (optional)"),
) -> None:
    """Test an agent provider with a simple prompt."""
    try:
        # Get provider enum if specified
        agent_provider: AgentProvider | None = None
        if provider:
            try:
                agent_provider = AgentProvider(provider.lower())
            except ValueError:
                console.print(f"[red]Unknown provider: {provider}[/red]")
                console.print(
                    f"Available: {', '.join(p.value for p in AgentProvider if p != AgentProvider.MOCK)}"
                )
                raise typer.Exit(1) from None

        agent = get_agent(agent_provider)
        console.print(f"[blue]Testing agent:[/blue] {agent.provider.value}")

        config = AgentConfig(
            model=model
            or ("claude-sonnet-4-20250514" if agent.provider == AgentProvider.CLAUDE else "gpt-4o"),
            max_tokens=100,
            temperature=0.7,
        )

        console.print(f"[blue]Model:[/blue] {config.model}")
        console.print(f"[blue]Prompt:[/blue] {prompt}")
        console.print()

        # Run the test
        with console.status("Waiting for response..."):
            response = asyncio.run(
                agent.complete(
                    messages=[AgentMessage.user(prompt)],
                    config=config,
                )
            )

        console.print("[green]Response:[/green]")
        console.print(response.content)
        console.print()

        # Show metrics
        table = Table(title="Usage Metrics")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="right")

        table.add_row("Input Tokens", str(response.input_tokens))
        table.add_row("Output Tokens", str(response.output_tokens))
        table.add_row("Total Tokens", str(response.total_tokens))
        table.add_row("Est. Cost", f"${response.cost_estimate:.4f}")
        table.add_row("Stop Reason", response.stop_reason or "N/A")

        console.print(table)

    except AgentError as e:
        console.print(f"[red]Agent error:[/red] {e}")
        logger.error("agent_test_failed", error=str(e), provider=e.provider.value)
        raise typer.Exit(1) from None


@app.command("chat")
def chat_agent(
    provider: str = typer.Option(
        None,
        "--provider",
        "-p",
        help="Provider to use (claude, openai)",
    ),
    model: str = typer.Option(None, "--model", "-m", help="Model to use"),
    system: str = typer.Option(
        None,
        "--system",
        "-s",
        help="System prompt",
    ),
) -> None:
    """Start an interactive chat session with an agent."""
    try:
        # Get provider enum if specified
        agent_provider: AgentProvider | None = None
        if provider:
            try:
                agent_provider = AgentProvider(provider.lower())
            except ValueError:
                console.print(f"[red]Unknown provider: {provider}[/red]")
                raise typer.Exit(1) from None

        agent = get_agent(agent_provider)

        config = AgentConfig(
            model=model
            or ("claude-sonnet-4-20250514" if agent.provider == AgentProvider.CLAUDE else "gpt-4o"),
            max_tokens=4096,
            temperature=0.7,
            system_prompt=system,
        )

        console.print(f"[bold blue]Chat with {agent.provider.value}[/bold blue]")
        console.print(f"Model: {config.model}")
        console.print("Type 'exit' or 'quit' to end the session.")
        console.print()

        messages: list[AgentMessage] = []

        while True:
            try:
                user_input = console.input("[bold green]You:[/bold green] ")
            except (KeyboardInterrupt, EOFError):
                console.print("\n[yellow]Session ended[/yellow]")
                break

            if user_input.lower() in ("exit", "quit", "q"):
                console.print("[yellow]Session ended[/yellow]")
                break

            if not user_input.strip():
                continue

            messages.append(AgentMessage.user(user_input))

            try:
                with console.status("Thinking..."):
                    response = asyncio.run(agent.complete(messages=messages, config=config))

                console.print(f"[bold blue]{agent.provider.value}:[/bold blue] {response.content}")
                console.print(
                    f"[dim]({response.total_tokens} tokens, ${response.cost_estimate:.4f})[/dim]"
                )
                console.print()

                messages.append(AgentMessage.assistant(response.content))

            except AgentError as e:
                console.print(f"[red]Error:[/red] {e}")

    except AgentError as e:
        console.print(f"[red]Agent error:[/red] {e}")
        raise typer.Exit(1) from None
