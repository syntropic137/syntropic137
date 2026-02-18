"""Report generators."""

from syn_perf.reporters.console import ConsoleReporter
from syn_perf.reporters.json_report import JSONReporter

__all__ = [
    "ConsoleReporter",
    "JSONReporter",
]
