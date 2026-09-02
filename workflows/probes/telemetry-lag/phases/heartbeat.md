---
model: sonnet
allowed-tools: Bash,Write
timeout-seconds: 600
---

Emit timestamped markers at fixed intervals. This is an instrument, not a
research task - follow it exactly and do not improvise.

## What to do

Run EXACTLY this, once, and let it finish:

```
for i in $(seq 1 12); do
  echo "marker $i $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a /tmp/heartbeat.log
  sleep 10
done < /dev/null
```

That takes about two minutes and produces twelve markers ten seconds apart.

`< /dev/null` is deliberate. A shell call that waits on stdin never returns,
and an unreturned call is indistinguishable from a hang - which is the exact
confusion this probe exists to resolve.

Then, and only then:

1. `cat /tmp/heartbeat.log` so every marker appears in the transcript.
2. Write the full contents of that log to the output directory as markdown,
   under a heading `## Markers`, one per line, unmodified.
3. Below it, add a heading `## Self-report` with:
   - the wall-clock time you started the loop
   - the wall-clock time you finished it
   - the number of markers emitted

## Do not

- Do not run anything else. Every extra tool call adds an event and blurs the
  measurement.
- Do not shorten the loop, batch the markers, or replace `sleep` with anything.
  The fixed cadence IS the measurement.
- Do not summarise, analyse or comment. The markers are the deliverable.
