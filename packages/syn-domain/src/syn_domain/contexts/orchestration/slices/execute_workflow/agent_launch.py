"""What a phase's agent is launched with: its argv and the environment it adds.

A harness command line is visible to every process in the workspace through
``/proc/<pid>/cmdline``, so ``ps aux | grep <pattern>`` and ``pgrep -f`` read
it. When the task prompt rode in argv, any agent that cleaned up "its" stray
process by a pattern taken from its own task matched the harness too, and
SIGTERMed itself (#2355). The prompt therefore travels in ``environment`` and
reaches the harness on stdin; ``argv`` carries flags only.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AgentLaunch:
    """The argv a phase's agent runs and the environment it needs beside the agent env.

    ``environment`` is merged over the agent env the handler builds, so the
    names here are the launch's own (the prompt), never credentials.
    """

    argv: tuple[str, ...]
    environment: dict[str, str] = field(default_factory=dict[str, str])
