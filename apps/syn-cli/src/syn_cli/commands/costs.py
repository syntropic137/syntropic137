"""Cost tracking commands — summary, sessions, executions."""

from __future__ import annotations

import typer
from rich.panel import Panel
from rich.table import Table

from syn_cli._output import (
    console,
    format_breakdown,
    format_cost,
    format_duration,
    format_timestamp,
    format_tokens,
    print_error,
)
from syn_cli.client import get_client
from syn_cli.commands._cost_models import (
    CostSummaryResponse,
    ExecutionCostResponse,
    SessionCostResponse,
)

app = typer.Typer(
    name="costs",
    help="View cost tracking data for sessions and executions",
    no_args_is_help=True,
)


def _safe_format_cost(value: str) -> str:
    """Format a cost string that may or may not already be $-prefixed."""
    if value.startswith("$"):
        return value
    try:
        return format_cost(value)
    except Exception:
        return value


def _handle_connect_error() -> None:
    from syn_cli.client import get_api_url

    print_error(f"Could not connect to API at {get_api_url()}")
    console.print("[dim]Make sure the API server is running.[/dim]")
    raise typer.Exit(1)


@app.command("summary")
def cost_summary() -> None:
    """Show aggregated cost summary across all sessions and executions."""
    try:
        with get_client() as client:
            resp = client.get("/costs/summary")
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code != 200:
        print_error(resp.json().get("detail", f"HTTP {resp.status_code}"))
        raise typer.Exit(1)

    data = CostSummaryResponse(**resp.json())
    panel_text = (
        f"[bold]Total Cost:[/bold] {format_cost(data.total_cost_usd)}\n"
        f"[bold]Sessions:[/bold] {data.total_sessions}\n"
        f"[bold]Executions:[/bold] {data.total_executions}\n"
        f"[bold]Tokens:[/bold] {format_tokens(data.total_tokens)}\n"
        f"[bold]Tool Calls:[/bold] {data.total_tool_calls}"
    )
    console.print(Panel(panel_text, title="[cyan]Cost Summary[/cyan]", border_style="cyan"))

    if data.top_models:
        table = Table(title="Top Models")
        table.add_column("Model", style="cyan")
        table.add_column("Cost", justify="right")
        for entry in data.top_models:
            table.add_row(entry.get("model", "unknown"), entry.get("cost", "$0"))
        console.print(table)

    if data.top_sessions:
        table = Table(title="Top Sessions")
        table.add_column("Session", style="dim")
        table.add_column("Cost", justify="right")
        for entry in data.top_sessions:
            sid = entry.get("session_id", "unknown")
            table.add_row(sid[:12] + "..." if len(sid) > 12 else sid, entry.get("cost", "$0"))
        console.print(table)


@app.command("sessions")
def list_session_costs(
    execution_id: str | None = typer.Option(
        None, "--execution", "-e", help="Filter by execution ID"
    ),
    limit: int = typer.Option(50, "--limit", "-n", help="Max results", min=1, max=200),
) -> None:
    """List cost data for sessions."""
    try:
        with get_client() as client:
            params: dict[str, str | int] = {"limit": limit}
            if execution_id:
                params["execution_id"] = execution_id
            resp = client.get("/costs/sessions", params=params)
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code != 200:
        print_error(resp.json().get("detail", f"HTTP {resp.status_code}"))
        raise typer.Exit(1)

    items = [SessionCostResponse(**s) for s in resp.json()]
    if not items:
        console.print("[dim]No session cost data found.[/dim]")
        return

    table = Table(title="Session Costs")
    table.add_column("Session ID", style="dim")
    table.add_column("Cost", justify="right")
    table.add_column("Tokens", justify="right")
    table.add_column("Duration", justify="right")
    table.add_column("Tools", justify="right")

    for s in items:
        table.add_row(
            s.session_id[:12] + "..." if len(s.session_id) > 12 else s.session_id,
            format_cost(s.total_cost_usd),
            format_tokens(s.total_tokens),
            format_duration(s.duration_ms),
            str(s.tool_calls),
        )
    console.print(table)


@app.command("session")
def show_session_cost(
    session_id: str = typer.Argument(..., help="Session ID"),
) -> None:
    """Show detailed cost breakdown for a session."""
    try:
        with get_client() as client:
            resp = client.get(f"/costs/sessions/{session_id}")
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code != 200:
        print_error(resp.json().get("detail", f"HTTP {resp.status_code}"))
        raise typer.Exit(1)

    s = SessionCostResponse(**resp.json())
    panel_text = (
        f"[bold]Session:[/bold] {s.session_id}\n"
        f"[bold]Cost:[/bold] {format_cost(s.total_cost_usd)}\n"
        f"[bold]Tokens:[/bold] {format_tokens(s.total_tokens)} "
        f"(in: {format_tokens(s.input_tokens)}, out: {format_tokens(s.output_tokens)})\n"
        f"[bold]Tool Calls:[/bold] {s.tool_calls}  [bold]Turns:[/bold] {s.turns}\n"
        f"[bold]Duration:[/bold] {format_duration(s.duration_ms)}\n"
        f"[bold]Started:[/bold] {format_timestamp(s.started_at)}"
    )
    console.print(Panel(panel_text, title="[cyan]Session Cost Detail[/cyan]", border_style="cyan"))

    if s.cost_by_model:
        console.print(format_breakdown(s.cost_by_model, "Cost by Model", _safe_format_cost))
    if s.cost_by_tool:
        console.print(format_breakdown(s.cost_by_tool, "Cost by Tool", _safe_format_cost))


@app.command("executions")
def list_execution_costs(
    limit: int = typer.Option(50, "--limit", "-n", help="Max results", min=1, max=200),
) -> None:
    """List cost data for workflow executions."""
    try:
        with get_client() as client:
            resp = client.get("/costs/executions", params={"limit": limit})
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code != 200:
        print_error(resp.json().get("detail", f"HTTP {resp.status_code}"))
        raise typer.Exit(1)

    items = [ExecutionCostResponse(**e) for e in resp.json()]
    if not items:
        console.print("[dim]No execution cost data found.[/dim]")
        return

    table = Table(title="Execution Costs")
    table.add_column("Execution ID", style="dim")
    table.add_column("Cost", justify="right")
    table.add_column("Sessions", justify="right")
    table.add_column("Tokens", justify="right")

    for e in items:
        table.add_row(
            e.execution_id[:12] + "..." if len(e.execution_id) > 12 else e.execution_id,
            format_cost(e.total_cost_usd),
            str(e.session_count),
            format_tokens(e.total_tokens),
        )
    console.print(table)


@app.command("execution")
def show_execution_cost(
    execution_id: str = typer.Argument(..., help="Execution ID"),
) -> None:
    """Show detailed cost breakdown for an execution."""
    try:
        with get_client() as client:
            resp = client.get(f"/costs/executions/{execution_id}")
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code != 200:
        print_error(resp.json().get("detail", f"HTTP {resp.status_code}"))
        raise typer.Exit(1)

    e = ExecutionCostResponse(**resp.json())
    panel_text = (
        f"[bold]Execution:[/bold] {e.execution_id}\n"
        f"[bold]Cost:[/bold] {format_cost(e.total_cost_usd)}\n"
        f"[bold]Sessions:[/bold] {e.session_count}\n"
        f"[bold]Tokens:[/bold] {format_tokens(e.total_tokens)} "
        f"(in: {format_tokens(e.input_tokens)}, out: {format_tokens(e.output_tokens)})\n"
        f"[bold]Duration:[/bold] {format_duration(e.duration_ms)}\n"
        f"[bold]Started:[/bold] {format_timestamp(e.started_at)}"
    )
    console.print(
        Panel(panel_text, title="[cyan]Execution Cost Detail[/cyan]", border_style="cyan")
    )

    if e.cost_by_phase:
        console.print(format_breakdown(e.cost_by_phase, "Cost by Phase", _safe_format_cost))
    if e.cost_by_model:
        console.print(format_breakdown(e.cost_by_model, "Cost by Model", _safe_format_cost))
    if e.cost_by_tool:
        console.print(format_breakdown(e.cost_by_tool, "Cost by Tool", _safe_format_cost))
