"""Entry point for the agent runner.

This module is executed when running:
    python -m aef_agent_runner

It loads the task from /workspace/task.json, executes the agent,
and emits events to stdout as JSONL.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from aef_agent_runner.cancellation import CancellationError, CancellationToken
from aef_agent_runner.events import emit_error
from aef_agent_runner.runner import AgentRunner
from aef_agent_runner.task import Task

# Configure logging to stderr (stdout is for events)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)

logger = logging.getLogger(__name__)

# Default paths inside workspace container
# task.json is injected via inject_context which writes to .context/
DEFAULT_TASK_PATH = Path("/workspace/.context/task.json")
DEFAULT_OUTPUT_DIR = Path("/workspace/artifacts")
DEFAULT_CANCEL_PATH = Path("/workspace/.cancel")


def main(
    task_path: Path | None = None,
    output_dir: Path | None = None,
    cancel_path: Path | None = None,
) -> int:
    """Main entry point for the agent runner.

    Args:
        task_path: Path to task.json (default: /workspace/task.json)
        output_dir: Directory for output artifacts (default: /workspace/artifacts)
        cancel_path: Path to cancellation file (default: /workspace/.cancel)

    Returns:
        Exit code (0 = success, 1 = error, 130 = cancelled)
    """
    task_path = task_path or DEFAULT_TASK_PATH
    output_dir = output_dir or DEFAULT_OUTPUT_DIR
    cancel_path = cancel_path or DEFAULT_CANCEL_PATH

    logger.info("Agent runner starting")
    logger.info("Task file: %s", task_path)
    logger.info("Output dir: %s", output_dir)
    logger.info("Cancel file: %s", cancel_path)

    try:
        # Load task
        task = Task.from_file(task_path)
        logger.info(
            "Task loaded: phase=%s, execution=%s, tenant=%s",
            task.phase,
            task.execution_id,
            task.tenant_id,
        )

        # Create cancellation token
        cancel_token = CancellationToken(cancel_path)

        # Create and run the agent
        runner = AgentRunner(
            task=task,
            output_dir=output_dir,
            cancel_token=cancel_token,
        )

        # Run the agent (events are emitted to stdout by the runner)
        runner.run()

        logger.info("Agent runner completed successfully")
        return 0

    except FileNotFoundError as e:
        logger.error("Task file not found: %s", e)
        emit_error(message=str(e), error_type="FileNotFoundError")
        return 1

    except ValueError as e:
        logger.error("Invalid task: %s", e)
        emit_error(message=str(e), error_type="ValueError")
        return 1

    except CancellationError:
        logger.info("Agent runner cancelled")
        return 130  # SIGINT equivalent

    except Exception as e:
        logger.exception("Agent runner failed with unexpected error")
        emit_error(message=str(e), error_type=type(e).__name__)
        return 1


if __name__ == "__main__":
    sys.exit(main())
