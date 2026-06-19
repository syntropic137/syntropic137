# Verdict

Verdict: inconclusive

## Hypothesis scorecard
| # | Predicted | Observed | Score | Notes |
|---|---|---|---|---|
| H1 | C1 exports OTLP (>=1 record), parity=wiring | C1 had 0 `OTLP_*` rows, but the interactive turn did not complete | PARTIAL | Not a valid telemetry score because the condition never produced a model answer. Evidence: `runs/c1-turn-completed.txt`, `runs/c1-after-delta.tsv`. |
| H2 | C1 hook events == 0 | C1 hook delta was 0, but the interactive turn did not complete | PARTIAL | The observed count is 0, but the incomplete turn prevents a meaningful channel verdict. Evidence: `runs/c1-after-delta.tsv`. |
| H3 | C2 == 0 | C2 total delta was 0, but the interactive turn did not complete | PARTIAL | The observed count is 0, but the incomplete turn makes this a confounded control. Evidence: `runs/c2-turn-completed.txt`, `runs/c2-after-delta.tsv`. |
| H4 | C3 reachable (2xx/4xx) | HTTP 200 from inside C1 to `http://syn-collector:8080/v1/metrics` | PASS | Collector network reachability passed. Evidence: `runs/c3-http-code.txt`, `runs/c3-curl-exit-status.txt`. |
| C0 | baseline >=3 OTLP | C0 completed and answered `4`, but `OTLP_*` delta was 0 | FAIL | This prediction was wrong for the frozen run: the baseline pipeline did not produce the required OTLP rows. Evidence: `runs/c0-claude-answer.txt`, `runs/c0-after-delta.tsv`. |

## What this means for the release
The frozen mapping requires `inconclusive`: C0 sanity failed, and C1/C2 never completed model turns. This run does not justify either a wiring-only release fix or committing to the event-capture arc; first unblock the baseline OTLP pipeline and the interactive workspace trust automation, then rerun to resolve the plugin-hook gap.
