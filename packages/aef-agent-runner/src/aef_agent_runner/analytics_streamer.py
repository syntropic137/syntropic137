"""Real-time analytics event streamer.

Watches .agentic/analytics/ directory and streams new events
to stdout as JSONL. These events are parsed by execute_streaming
in the orchestrator and forwarded to the control plane.

Uses file tail-like approach to stream new lines as they are appended.

Example usage:
    from aef_agent_runner.analytics_streamer import AnalyticsStreamer
    from aef_shared.workspace_paths import WORKSPACE_ANALYTICS_DIR

    streamer = AnalyticsStreamer(WORKSPACE_ANALYTICS_DIR)
    streamer.start()  # Starts background thread
    # ... agent runs and hooks write to events.jsonl ...
    streamer.stop()

Events are emitted to stdout in this format:
    {"type": "analytics", "source": "hook", "data": {...}}
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class AnalyticsStreamer:
    """Background streamer that tails analytics files and emits events.

    Watches a directory for JSONL files and streams new lines to stdout.
    Uses polling instead of inotify for cross-platform compatibility.
    """

    def __init__(
        self,
        analytics_dir: Path,
        poll_interval: float = 0.5,
    ):
        """Initialize the analytics streamer.

        Args:
            analytics_dir: Directory containing analytics files (e.g., events.jsonl)
            poll_interval: How often to check for new data (seconds)
        """
        self.analytics_dir = Path(analytics_dir)
        self.poll_interval = poll_interval
        self._file_positions: dict[Path, int] = {}
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the background streaming thread."""
        if self._running:
            logger.warning("AnalyticsStreamer already running")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._watch_loop,
            daemon=True,
            name="analytics-streamer",
        )
        self._thread.start()
        logger.info("AnalyticsStreamer started watching: %s", self.analytics_dir)

    def stop(self) -> None:
        """Stop the background streaming thread."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        logger.info("AnalyticsStreamer stopped")

    def _watch_loop(self) -> None:
        """Main polling loop that checks for new data."""
        while self._running:
            try:
                self._check_for_new_data()
            except Exception as e:
                logger.error("Error checking analytics: %s", e)
            time.sleep(self.poll_interval)

    def _check_for_new_data(self) -> None:
        """Check all JSONL files for new lines."""
        if not self.analytics_dir.exists():
            return

        for jsonl_file in self.analytics_dir.glob("*.jsonl"):
            self._stream_new_lines(jsonl_file)

    def _stream_new_lines(self, path: Path) -> None:
        """Read and emit any new lines from a file.

        Tracks file positions to only emit new data.
        """
        pos = self._file_positions.get(path, 0)

        try:
            with path.open(encoding="utf-8") as f:
                # Seek to last known position
                f.seek(pos)

                # Read all new lines
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        # Parse the hook event
                        data = json.loads(line)

                        # Wrap in analytics envelope
                        envelope = {
                            "type": "analytics",
                            "source": "hook",
                            "data": data,
                        }

                        # Emit to stdout (will be captured by execute_streaming)
                        print(json.dumps(envelope), flush=True)

                    except json.JSONDecodeError as e:
                        logger.warning("Invalid JSON in analytics file: %s", e)

                # Update position
                self._file_positions[path] = f.tell()

        except FileNotFoundError:
            # File was deleted, reset position
            self._file_positions.pop(path, None)
        except PermissionError as e:
            logger.warning("Cannot read analytics file: %s", e)


def create_streamer_from_env() -> AnalyticsStreamer:
    """Create an analytics streamer using workspace paths.

    Returns:
        Configured AnalyticsStreamer instance
    """
    from aef_shared.workspace_paths import WORKSPACE_ANALYTICS_DIR

    return AnalyticsStreamer(Path(str(WORKSPACE_ANALYTICS_DIR)))
