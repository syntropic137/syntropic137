"""``python -m syn_perf.loadtest --n N --tier platform|node`` (#1717).

Exit status: 0 the pass bar held, 1 it did not (the report says which check),
2 the run was refused (a profile that does not validate before anything is
sent; a real model in a session or an API that failed a read during the run).
A run refused after admission began still writes its report.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Annotated, Literal

import typer
from pydantic import TypeAdapter, ValidationError

from syn_domain.contexts.orchestration import WorkflowDefinition
from syn_perf.loadtest.driver import Pacing, Target, run_load_test
from syn_perf.loadtest.pass_bar import (
    NORTH_STAR_ADMIT_SECONDS,
    NORTH_STAR_READ_P95_SECONDS,
    NORTH_STAR_SUSTAIN_SECONDS,
    ContainerRoles,
    PassBar,
)
from syn_perf.loadtest.scripted_agent_profile import (
    NoWorkload,
    ScriptedAgentProfile,
    ScriptedStream,
)
from syn_shared.settings.constants import DEFAULT_SELFHOST_API_URL, ENV_SYN_API_URL

_REPO = Path(__file__).resolve().parents[5]
_WORKFLOW = _REPO / "workflows/sdlc/implement-v3/workflow.yaml"
_STREAMS = TypeAdapter(dict[str, ScriptedStream])

app = typer.Typer(add_completion=False)


@app.command()
def main(
    n: Annotated[int, typer.Option("--n", min=1, help="Executions to admit")],
    streams: Annotated[
        Path,
        typer.Option(
            exists=True,
            dir_okay=False,
            help="JSON: phase id -> ScriptedStream (recording, tool_uses, ...)",
        ),
    ],
    fixture_repo: Annotated[
        str, typer.Option(help="owner/name the stub pushes to; sent as every start's repos")
    ],
    api_container: Annotated[str, typer.Option(help="API container name to sample")],
    postgres_container: Annotated[str, typer.Option(help="Postgres container name")],
    event_store_container: Annotated[str, typer.Option(help="Event store container name")],
    socket_proxy_container: Annotated[str, typer.Option(help="Docker socket proxy container")],
    tier: Annotated[str, typer.Option(help="platform or node")] = "platform",
    api_url: Annotated[
        str | None, typer.Option(help=f"Defaults to ${ENV_SYN_API_URL}, then the selfhost gateway")
    ] = None,
    workflow: Annotated[Path, typer.Option(help="Workflow YAML the run stands in for")] = _WORKFLOW,
    admit_seconds: Annotated[float, typer.Option(min=0)] = NORTH_STAR_ADMIT_SECONDS,
    sustain_seconds: Annotated[float, typer.Option(min=0)] = NORTH_STAR_SUSTAIN_SECONDS,
    sample_seconds: Annotated[float, typer.Option(min=0.1)] = 5.0,
    drain_timeout_seconds: Annotated[float, typer.Option(min=0)] = 14400.0,
    read_p95_seconds: Annotated[
        float, typer.Option(min=0, help="Looser than the north star fails north_star_bar")
    ] = NORTH_STAR_READ_P95_SECONDS,
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
        api_url=api_url or os.environ.get(ENV_SYN_API_URL, DEFAULT_SELFHOST_API_URL),
        workflow_id=definition.id,
        task=f"Load test: {n} scripted executions, {tier} tier (#1717).",
        repos=(profile.fixture_repo,),
        containers=ContainerRoles(
            api=api_container,
            postgres=postgres_container,
            event_store=event_store_container,
            socket_proxy=socket_proxy_container,
        ),
    )
    result = asyncio.run(
        run_load_test(
            target,
            profile,
            PassBar(
                n=n,
                sustain_seconds=sustain_seconds,
                read_p95_seconds=read_p95_seconds,
                admit_seconds=admit_seconds,
            ),
            Pacing(admit_seconds, sample_seconds, drain_timeout_seconds),
        )
    )

    report.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    for check in result.checks:
        typer.echo(f"{'PASS' if check.passed else 'FAIL'}  {check.name}: {check.detail}")
    typer.echo(json.dumps({"passed": result.passed, "report": str(report)}))
    if result.refused is not None:
        typer.echo(f"refused: {result.refused}", err=True)
        sys.exit(2)
    sys.exit(0 if result.passed else 1)


if __name__ == "__main__":
    app()
