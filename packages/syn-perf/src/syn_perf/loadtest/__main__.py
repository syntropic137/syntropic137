"""``python -m syn_perf.loadtest --n N --tier platform|node`` (#1717).

Exit status: 0 the pass bar held, 1 it did not (the report says which check),
2 the run was refused before or during admission (a real model in a session,
a profile that does not validate, an API that rejected a start).
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Annotated, Literal

import httpx
import typer
from pydantic import TypeAdapter, ValidationError

from syn_domain.contexts.orchestration import WorkflowDefinition
from syn_perf.loadtest.driver import Pacing, Target, run_load_test
from syn_perf.loadtest.pass_bar import PassBar, RealHarnessError
from syn_perf.loadtest.scripted_agent_profile import (
    NoWorkload,
    ScriptedAgentProfile,
    ScriptedStream,
)

_REPO = Path(__file__).resolve().parents[5]
_WORKFLOW = _REPO / "workflows/sdlc/implement-v3/workflow.yaml"
_STREAMS = TypeAdapter(dict[str, ScriptedStream])

app = typer.Typer(add_completion=False)


@app.command()
def main(
    n: Annotated[int, typer.Option("--n", min=1, help="Executions to admit")],
    streams: Annotated[
        Path, typer.Option(help="JSON: phase id -> ScriptedStream (recording, tool_uses, ...)")
    ],
    fixture_repo: Annotated[str, typer.Option(help="owner/name the stub pushes to")],
    tier: Annotated[str, typer.Option(help="platform or node")] = "platform",
    api_url: Annotated[str, typer.Option()] = "http://localhost:18000",
    workflow: Annotated[Path, typer.Option(help="Workflow YAML the run stands in for")] = _WORKFLOW,
    admit_seconds: Annotated[float, typer.Option(min=0)] = 300.0,
    sustain_seconds: Annotated[float, typer.Option(min=0)] = 1800.0,
    sample_seconds: Annotated[float, typer.Option(min=0.1)] = 5.0,
    drain_timeout_seconds: Annotated[float, typer.Option(min=0)] = 14400.0,
    read_p95_seconds: Annotated[float, typer.Option(min=0)] = 2.0,
    container: Annotated[
        list[str] | None,
        typer.Option(help="Platform container to sample; repeat for API, Postgres, ES, proxy"),
    ] = None,
    report: Annotated[Path, typer.Option(help="Where to write the JSON report")] = Path(
        "loadtest-report.json"
    ),
    profile_out: Annotated[
        Path, typer.Option(help="Where to write the profile the stack's workspaces must read")
    ] = Path("loadtest-profile.json"),
) -> None:
    if tier not in ("platform", "node"):
        raise typer.BadParameter("--tier must be platform or node")
    the_tier: Literal["platform", "node"] = "platform" if tier == "platform" else "node"
    definition = WorkflowDefinition.from_file(workflow)
    try:
        profile = ScriptedAgentProfile.for_workflow(
            definition,
            tier=the_tier,
            fixture_repo=fixture_repo,
            streams=_STREAMS.validate_json(streams.read_bytes()),
            workload=NoWorkload(),
        )
    except (ValidationError, ValueError) as exc:
        typer.echo(f"refused: the scripted profile does not validate: {exc}", err=True)
        raise typer.Exit(2) from exc
    profile_out.write_text(profile.model_dump_json(indent=2), encoding="utf-8")

    target = Target(
        api_url=api_url,
        workflow_id=definition.id,
        task=f"Load test: {n} scripted executions, {tier} tier (#1717).",
        containers=tuple(container or ()),
    )
    try:
        result = asyncio.run(
            run_load_test(
                target,
                profile,
                PassBar(n=n, sustain_seconds=sustain_seconds, read_p95_seconds=read_p95_seconds),
                Pacing(admit_seconds, sample_seconds, drain_timeout_seconds),
            )
        )
    except RealHarnessError as exc:
        typer.echo(f"refused: {exc}", err=True)
        raise typer.Exit(2) from exc
    except httpx.HTTPError as exc:
        typer.echo(f"refused: the API at {api_url} failed a request: {exc!r}", err=True)
        raise typer.Exit(2) from exc

    report.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    for check in result.checks:
        typer.echo(f"{'PASS' if check.passed else 'FAIL'}  {check.name}: {check.detail}")
    typer.echo(json.dumps({"passed": result.passed, "report": str(report)}))
    sys.exit(0 if result.passed else 1)


if __name__ == "__main__":
    app()
