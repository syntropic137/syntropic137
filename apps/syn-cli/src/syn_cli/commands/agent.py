"""Agent interaction commands — list providers, test, chat."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table

from syn_cli._output import console, print_error
from syn_cli.client import get_client

app = typer.Typer(
    name="agent",
    help="AI agent management and testing",
    no_args_is_help=True,
)


def _handle_connect_error() -> None:
    from syn_cli.client import get_api_url

    print_error(f"Could not connect to API at {get_api_url()}")
    console.print("[dim]Make sure the API server is running.[/dim]")
    raise typer.Exit(1)


@app.command("list")
def list_providers() -> None:
    """List available agent providers."""
    try:
        with get_client() as client:
            resp = client.get("/agents/providers")
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code != 200:
        print_error(resp.json().get("detail", f"HTTP {resp.status_code}"))
        raise typer.Exit(1)

    providers = resp.json()
    if not isinstance(providers, list):
        providers = providers.get("providers", [])

    table = Table(title="Agent Providers")
    table.add_column("Provider", style="cyan")
    table.add_column("Display Name")
    table.add_column("Available")
    table.add_column("Default Model")

    for p in providers:
        available = "[green]Yes[/green]" if p.get("available") else "[red]No[/red]"
        table.add_row(
            p.get("provider", ""),
            p.get("display_name", ""),
            available,
            p.get("default_model", ""),
        )
    console.print(table)


@app.command("test")
def test_agent(
    provider: Annotated[
        str,
        typer.Option("--provider", "-p", help="Agent provider (claude, mock)"),
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
    try:
        with get_client() as client, console.status(f"Testing {provider}..."):
            resp = client.post(
                "/agents/test",
                json={"provider": provider, "prompt": prompt, "model": model},
                timeout=60.0,
            )
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code != 200:
        print_error(resp.json().get("detail", f"HTTP {resp.status_code}"))
        raise typer.Exit(1)

    result = resp.json()
    console.print(f"[green]Response from {result.get('provider', provider)}:[/green]")
    console.print(f"  Model: {result.get('model', 'unknown')}")
    console.print(f"  Response: {result.get('response_text', '')}")
    console.print(
        f"  Tokens: {result.get('input_tokens', 0)} in / {result.get('output_tokens', 0)} out"
    )


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

        try:
            with get_client() as client, console.status("Thinking..."):
                resp = client.post(
                    "/agents/chat",
                    json={"provider": provider, "messages": messages, "model": model},
                    timeout=120.0,
                )
        except Exception:
            print_error("Lost connection to API server")
            break

        if resp.status_code != 200:
            print_error(resp.json().get("detail", f"HTTP {resp.status_code}"))
            break

        result = resp.json()
        response_text = result.get("response_text", "")
        console.print(f"[bold green]Agent:[/bold green] {response_text}\n")
        messages.append({"role": "assistant", "content": response_text})
