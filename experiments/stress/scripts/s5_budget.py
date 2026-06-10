"""S5 — aggregate wall-time + quota signal review for the stress campaign."""

from __future__ import annotations

import json
import statistics
import subprocess
import sys
from pathlib import Path

API = "http://localhost:9137"
CAMPAIGN_CUTOFF = "2026-06-10T17:42"


def _fetch_executions() -> list[dict]:
    raw = subprocess.run(
        ["curl", "-sS", f"{API}/executions?limit=100&page_size=100"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return json.loads(raw).get("executions", [])


def _is_campaign_run(execution: dict) -> bool:
    workflow_id = execution.get("workflow_id", "")
    started_at = execution.get("started_at") or ""
    return workflow_id.endswith("-interactive") and started_at >= CAMPAIGN_CUTOFF


def _filter_campaign_runs(executions: list[dict]) -> list[dict]:
    runs = [e for e in executions if _is_campaign_run(e)]
    runs.sort(key=lambda e: e.get("started_at", ""))
    return runs


def _summarize_durations(durations: list[float]) -> dict[str, float | None]:
    if not durations:
        return {"min": None, "max": None, "avg": None, "median": None}
    return {
        "min": min(durations),
        "max": max(durations),
        "avg": sum(durations) / len(durations),
        "median": statistics.median(durations),
    }


def _status_counts(runs: list[dict]) -> dict[str, int]:
    return {
        "completed": sum(1 for e in runs if e["status"] == "completed"),
        "failed": sum(1 for e in runs if e["status"] == "failed"),
        "cancelled": sum(1 for e in runs if e["status"] == "cancelled"),
    }


def _quota_log_excerpt() -> list[str]:
    """Scrape syn-api logs for quota / refusal signals over the last hour."""
    cmd = (
        "docker logs --since 60m syn-api 2>&1 | "
        "grep -iE 'rate.limit|429|quota|too many requests|throttle|usage limit|"
        "refused|claude.*error|anthropic' | tail -50 || true"
    )
    proc = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
    return proc.stdout.splitlines()


def _build_summary(runs: list[dict]) -> dict:
    durations = [e["duration_seconds"] for e in runs if e.get("duration_seconds")]
    dur_stats = _summarize_durations(durations)
    counts = _status_counts(runs)
    return {
        "scenario": "S5-budget-reality",
        "campaign_cutoff": CAMPAIGN_CUTOFF,
        "executions_in_campaign": len(runs),
        "min_duration_seconds": dur_stats["min"],
        "max_duration_seconds": dur_stats["max"],
        "avg_duration_seconds": dur_stats["avg"],
        "median_duration_seconds": dur_stats["median"],
        "completed_count": counts["completed"],
        "failed_count": counts["failed"],
        "cancelled_count": counts["cancelled"],
        "total_tokens_observed": sum(int(e.get("total_tokens") or 0) for e in runs),
        "runs": [
            {
                "execution_id": e["workflow_execution_id"],
                "workflow_id": e["workflow_id"],
                "status": e["status"],
                "duration_seconds": e.get("duration_seconds"),
                "error_message": e.get("error_message"),
            }
            for e in runs
        ],
        "quota_log_excerpt": _quota_log_excerpt(),
    }


def main() -> int:
    runs = _filter_campaign_runs(_fetch_executions())
    summary = _build_summary(runs)
    out_path = Path(
        sys.argv[1] if len(sys.argv) > 1 else "experiments/stress/results/s5-budget.json"
    )
    out_path.write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2)[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
