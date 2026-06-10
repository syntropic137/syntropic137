"""S5 — aggregate wall-time + quota signal review for the stress campaign."""

from __future__ import annotations

import json
import statistics
import subprocess
import sys
from pathlib import Path

API = "http://localhost:9137"


def main() -> int:
    raw = subprocess.run(
        ["curl", "-sS", f"{API}/executions?limit=100&page_size=100"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    data = json.loads(raw)
    campaign_cutoff = "2026-06-10T17:42"
    runs = [
        e
        for e in data.get("executions", [])
        if e.get("workflow_id", "").endswith("-interactive")
        and (e.get("started_at") or "") >= campaign_cutoff
    ]
    runs.sort(key=lambda e: e.get("started_at", ""))

    durations = [e["duration_seconds"] for e in runs if e.get("duration_seconds")]
    summary = {
        "scenario": "S5-budget-reality",
        "campaign_cutoff": campaign_cutoff,
        "executions_in_campaign": len(runs),
        "min_duration_seconds": min(durations) if durations else None,
        "max_duration_seconds": max(durations) if durations else None,
        "avg_duration_seconds": (sum(durations) / len(durations)) if durations else None,
        "median_duration_seconds": statistics.median(durations) if durations else None,
        "completed_count": sum(1 for e in runs if e["status"] == "completed"),
        "failed_count": sum(1 for e in runs if e["status"] == "failed"),
        "cancelled_count": sum(1 for e in runs if e["status"] == "cancelled"),
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
    }

    # Quota / refusal signals
    quota_log = subprocess.run(
        [
            "bash",
            "-c",
            "docker logs --since 60m syn-api 2>&1 | grep -iE 'rate.limit|429|quota|too many requests|throttle|usage limit|refused|claude.*error|anthropic' | tail -50 || true",
        ],
        capture_output=True,
        text=True,
    ).stdout
    summary["quota_log_excerpt"] = quota_log.splitlines()

    out_path = Path(sys.argv[1] if len(sys.argv) > 1 else "experiments/stress/results/s5-budget.json")
    out_path.write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2)[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
