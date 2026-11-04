# dreamship-implement-v6

Implement a DreamShip bead behind a failing test and open the PR, have Codex try
to falsify it, then fix what the review blocked on. Identical to v5 except the
phase timeouts. v5 existed only as database state on the VPS; this package was
exported from it (`syn workflow export dreamship-implement-v5`) so the workflow
is in source control from v6 on.

## Usage

```bash
syn workflow install workflows/dreamship/implement-v6
syn workflow run dreamship-implement-v6 --repo AweHelm/dream-ship-os -t "<bead id and spec>"
```

## Phases

| Phase | Agent | v5 timeout | v6 timeout |
|---|---|---|---|
| implement | claude opus | 5400 | 7200 |
| review | codex gpt-sol | 2400 | 3000 |
| remediate | claude opus | 2400 | 3600 |

## Why these timeouts (#2172)

Every `dreamship-*` phase that failed with exit 124 (25 runs, 2026-09-17 to
10-05) died at its own configured `timeout_seconds`, within about 3% of it.
There is no separate workspace cap underneath: the phase budget is the limit.

Completed phases (all `dreamship-*` versions, from `GET /executions/{id}`):

- **implement:** 41 completions, median about 3,560 s; 10 of them finished in the
  last 600 s before the 5,400 s cap, and 18 more were killed at it. The
  distribution is cut off by the cap, not finished under it.
- **review:** 15 completions up to 2,445 s, against a 2,400 s cap in v5.
- **remediate:** 9 completions up to 2,123 s; 4 v5 runs were killed at 2,400 s
  holding unpushed work.

The new values give each phase about a third more room than the crowded edge
of its distribution. They are a starting point to measure, not a final answer:
the DreamShip head-to-head (#2174) records phase durations again, and beads for
it are sized to 1-3 hours of work.

The agent is told its deadline (#1546, PR #1578), so finished work should be
pushed before the cap rather than held when it hits.
