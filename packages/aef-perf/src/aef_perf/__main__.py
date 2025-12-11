"""CLI entry point for aef-perf.

Usage:
    uv run python -m aef_perf --help
    uv run python -m aef_perf single --iterations 10
"""

from aef_perf.cli import app

if __name__ == "__main__":
    app()
