"""Task definition for agent execution.

The task is loaded from /workspace/task.json and contains all the
information needed for the agent to execute a workflow phase.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class Task:
    """Task configuration for agent execution.

    Loaded from /workspace/task.json by the orchestrator before
    starting the agent runner.
    """

    # Phase information
    phase: str
    prompt: str

    # Execution context
    execution_id: str
    tenant_id: str

    # Optional inputs from workflow
    inputs: dict[str, Any] = field(default_factory=dict)

    # Names of artifact files from previous phases (in /workspace/inputs/)
    artifacts: list[str] = field(default_factory=list)

    # Optional phase-specific configuration
    config: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_file(cls, path: Path) -> Task:
        """Load task from JSON file.

        Args:
            path: Path to task.json file

        Returns:
            Parsed Task instance

        Raises:
            FileNotFoundError: If task file doesn't exist
            ValueError: If task file is invalid
        """
        if not path.exists():
            msg = f"Task file not found: {path}"
            raise FileNotFoundError(msg)

        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            msg = f"Invalid JSON in task file: {e}"
            raise ValueError(msg) from e

        # Validate required fields
        required = ["phase", "prompt", "execution_id", "tenant_id"]
        missing = [f for f in required if f not in data]
        if missing:
            msg = f"Missing required fields in task: {missing}"
            raise ValueError(msg)

        return cls(
            phase=data["phase"],
            prompt=data["prompt"],
            execution_id=data["execution_id"],
            tenant_id=data["tenant_id"],
            inputs=data.get("inputs", {}),
            artifacts=data.get("artifacts", []),
            config=data.get("config", {}),
        )

    def get_artifact_paths(self, inputs_dir: Path) -> list[Path]:
        """Get full paths to input artifacts.

        Args:
            inputs_dir: Directory containing input artifacts

        Returns:
            List of paths to artifact files
        """
        return [inputs_dir / name for name in self.artifacts]

    def build_system_prompt(self) -> str:
        """Build the system prompt for the agent.

        Combines the phase prompt with artifact context.
        """
        parts = [self.prompt]

        if self.artifacts:
            parts.append("\n\n## Available Input Artifacts\n")
            for name in self.artifacts:
                parts.append(f"- `/workspace/inputs/{name}`")

        if self.inputs:
            parts.append("\n\n## Workflow Inputs\n")
            for key, value in self.inputs.items():
                parts.append(f"- **{key}**: {value}")

        parts.append("\n\n## Output\n")
        parts.append("Write any output artifacts to `/workspace/artifacts/`")

        return "\n".join(parts)
