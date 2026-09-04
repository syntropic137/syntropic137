---
model: sonnet
allowed-tools: Bash,Write
timeout-seconds: 600
---

Emit timestamped markers at fixed intervals. This is an instrument, not a
research task - follow it exactly and do not improvise.

## The task

$ARGUMENTS

## What to do

Run EXACTLY this, once, and let it finish:

```
LOG=$(mktemp /tmp/heartbeat.XXXXXX)
set -u
for i in $(seq 1 12); do
  printf '%s %s %s\n' "marker" "$i" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG" || exit 1
  if [ "$i" -lt 12 ]; then
    sleep 10 || exit 1
  fi
done
echo "COUNT=$(wc -l < "$LOG")"
cat "$LOG"
```

Notes on why it is written this way, so you do not "improve" it:

- `mktemp` gives a fresh file per run. Appending to a fixed path would mix this
  run's markers with a previous run's and the result would look plausible.
- The last iteration does not sleep. Sleeping after the final marker adds ten
  seconds of dead time that a later reader would mistake for work.
- `|| exit 1` on BOTH the write and the sleep. A failed write would otherwise be
  masked by the sleeps after it, and an interrupted `sleep` would let the loop
  finish twelve markers at the wrong cadence - a successful-looking artifact
  from a run that did not measure what it claims.
- `COUNT` is emitted by the shell, not by you. It is the only trustworthy count.

## Then

1. Verify `COUNT=12`. If it is anything else, say so plainly and report the
   actual number - a short run is a valid finding, a short run reported as
   twelve is a fabricated one.
2. Write the deliverable to the output directory as markdown:
   - `## Markers` - the exact lines from the log, unmodified, one per line.
   - `## Count` - the `COUNT=` value the shell printed.

## Do not

- Do not run anything else. Every extra tool call adds an event and blurs the
  measurement.
- Do not shorten the loop, batch the markers, or replace `sleep`. The fixed
  cadence IS the measurement.
- Do not write timings from memory. Every timestamp in the deliverable must be
  copied from the log. A self-reported start and end time is exactly the kind of
  unverifiable claim this probe exists to replace.
- Do not summarise or analyse. The markers are the deliverable.
