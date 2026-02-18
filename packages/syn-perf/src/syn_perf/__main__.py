"""CLI entry point for syn-perf.

Usage:
    uv run python -m syn_perf --help
    uv run python -m syn_perf single --iterations 10
"""

from syn_perf.cli import app

if __name__ == "__main__":
    app()
