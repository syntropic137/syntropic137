"""Agent interaction commands — list providers, test, chat."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table

from aef_api.types import Err, Ok
from aef_cli._async import run
from aef_cli._output import console

app = typer.Typer(
    name="agent",
    help="AI agent management and testing",
    no_args_is_help=True,
)


@app.command("list")
def list_providers() -> None:
    """List available agent providers."""
    import aef_api.v1.agents as ag

    result = run(ag.list_providers())

    match result:
        case Ok(providers):
            table = Table(title="Agent Providers")
            table.add_column("Provider", style="cyan")
            table.add_column("Display Name")
            table.add_column("Available")
            table.add_column("Default Model")

            for p in providers:
                available = "[green]Yes[/green]" if p.available else "[red]No[/red]"
                table.add_row(p.provider, p.display_name, available, p.default_model)
            console.print(table)
        case Err(error, message=msg):
            console.print(f"[red]{msg or error}[/red]")
            raise typer.Exit(1)


@app.command("test")
def test_agent(
    provider: Annotated[
        str,
        typer.Option("--provider", "-p", help="Agent provider (claude, openai, mock)"),
    ] = "claude",
    prompt: Annotated[
        str,
        typer.Option("--prompt", help="Test prompt"),
    ] = "Say hello in one sentence.",
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="Model override"),
    ] = None,
) -> None:
    """Test an agent provider with a simple prompt."""
    import aef_api.v1.agents as ag

    with console.status(f"Testing {provider}..."):
        result = run(ag.test_agent(provider=provider, prompt=prompt, model=model))

    match result:
        case Ok(test_result):
            console.print(f"[green]Response from {test_result.provider}:[/green]")
            console.print(f"  Model: {test_result.model}")
            console.print(f"  Response: {test_result.response_text}")
            console.print(
                f"  Tokens: {test_result.input_tokens} in / {test_result.output_tokens} out"
            )
        case Err(error, message=msg):
            console.print(f"[red]{msg or error}[/red]")
            raise typer.Exit(1)


@app.command("chat")
def chat_session(
    provider: Annotated[
        str,
        typer.Option("--provider", "-p", help="Agent provider"),
    ] = "claude",
    system: Annotated[
        str | None,
        typer.Option("--system", "-s", help="System prompt"),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="Model override"),
    ] = None,
) -> None:
    """Start an interactive chat session."""
    import aef_api.v1.agents as ag

    console.print(f"[bold]Chat with {provider}[/bold] (type 'exit' to quit)\n")

    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})

    while True:
        try:
            user_input = console.input("[bold blue]You:[/bold blue] ")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye![/dim]")
            break

        if user_input.strip().lower() in ("exit", "quit", "q"):
            console.print("[dim]Goodbye![/dim]")
            break

        if not user_input.strip():
            continue

        messages.append({"role": "user", "content": user_input})

        with console.status("Thinking..."):
            result = run(ag.chat(provider=provider, messages=messages, model=model))

        match result:
            case Ok(chat_result):
                console.print(f"[bold green]Agent:[/bold green] {chat_result.response_text}\n")
                messages.append({"role": "assistant", "content": chat_result.response_text})
            case Err(error, message=msg):
                console.print(f"[red]{msg or error}[/red]\n")
                break
