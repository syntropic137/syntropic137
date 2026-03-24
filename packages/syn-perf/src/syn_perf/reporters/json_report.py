"""JSON reporter for CI/automation integration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from syn_perf.metrics import TimingStats

if TYPE_CHECKING:
    from syn_perf.benchmarks.compare_result import BackendComparisonResult
    from syn_perf.metrics import BenchmarkResult


class JSONReporter:
    """Generate JSON reports for benchmark results."""

    def generate_report(
        self,
        result: BenchmarkResult,
        include_timings: bool = True,
    ) -> dict:
        """Generate JSON report for a benchmark result.

        Args:
            result: Benchmark result
            include_timings: Include individual timing data

        Returns:
            Dictionary ready for JSON serialization
        """
        report = result.to_dict()

        # Add computed statistics
        if result.create_times_ms:
            report["statistics"] = {
                "create": TimingStats.from_timings(result.create_times_ms).to_dict(),
                "destroy": TimingStats.from_timings(result.destroy_times_ms).to_dict(),
                "total": TimingStats.from_timings(result.total_times_ms).to_dict(),
            }

        if not include_timings:
            del report["timings"]

        return report

    def generate_comparison_report(
        self,
        result: BackendComparisonResult,
        include_timings: bool = False,
    ) -> dict:
        """Generate JSON report for backend comparison.

        Args:
            result: Comparison result
            include_timings: Include individual timing data

        Returns:
            Dictionary ready for JSON serialization
        """
        report: dict[str, Any] = {
            "available_backends": result.available_backends,
            "unavailable_backends": result.unavailable_backends,
            "best_backend": result.best_backend,
            "backends": {},
        }

        for backend, bench_result in result.results.items():
            stats = result.get_stats(backend)
            backend_report = {
                "iterations": bench_result.iterations,
                "success_rate": bench_result.success_rate,
                "statistics": {
                    "create": stats["create"].to_dict() if stats else {},
                    "destroy": stats["destroy"].to_dict() if stats else {},
                    "total": stats["total"].to_dict() if stats else {},
                },
            }

            if include_timings:
                backend_report["timings"] = [
                    {
                        "workspace_id": t.workspace_id,
                        "create_time_ms": t.create_time_ms,
                        "destroy_time_ms": t.destroy_time_ms,
                        "total_time_ms": t.total_time_ms,
                        "success": t.success,
                    }
                    for t in bench_result.timings
                ]

            report["backends"][backend] = backend_report

        return report

    def save(self, report: dict, path: Path | str) -> None:
        """Save report to JSON file.

        Args:
            report: Report dictionary
            path: Output file path
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, default=str))
