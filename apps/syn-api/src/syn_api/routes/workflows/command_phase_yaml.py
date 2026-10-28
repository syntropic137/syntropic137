"""A command phase's ``kind`` and ``commands`` in the workflow export (ADR-078).

Split from ``queries`` so the route module stays under the file-size fitness
threshold. Emitted so an exported command phase reinstalls as itself: dropped,
it would reinstall as an agent phase with no prompt."""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_api.routes.workflows.yaml_scalars import _yaml_quote

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syn_api.types import CommandStepResponse


def command_phase_yaml_lines(steps: Sequence[CommandStepResponse]) -> list[str]:
    """``kind: command`` and each step, with defaults left out as the loader reads them."""
    lines = ["    kind: command", "    commands:"]
    for step in steps:
        lines.append(f"      - name: {step.name}")
        lines.append(f"        run: {_yaml_quote(step.run)}")
        if step.timeout_seconds is not None:
            lines.append(f"        timeout_seconds: {step.timeout_seconds}")
        if step.allow_failure:
            lines.append("        allow_failure: true")
    return lines
