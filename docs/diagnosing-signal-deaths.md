# Diagnosing a signal death (exit -11 and friends)

`exit -11` is SIGSEGV. It is the most expensive failure class the platform has:
it has taken the unpushed-work gate's `git rev-parse`, the `find` over
`/workspace/repos`, the ADR-024 secret injection before any agent ran, and
whole phases with `tokens=0+0` and no terminal event - each one a phase's
budget spent for no output. Issues
[#1138](https://github.com/syntropic137/syntropic137/issues/1138) and
[#1295](https://github.com/syntropic137/syntropic137/issues/1295) disagree about
whether those are one bug or several, and the disagreement has been
unresolvable because the evidence was destroyed with the workspace.

## What the platform captures on its own

When a workspace command or the agent process dies on a signal, the backend
captures a diagnostic **at the moment it reaps the process** - not later,
because the reap removes the container and there is nothing left to read
(same requirement as [#1319](https://github.com/syntropic137/syntropic137/issues/1319)
for exit codes). Two capture sites, covering every shape observed so far:

| Site | Covers |
|---|---|
| `AgenticIsolationAdapter.execute()` | every short command - the gate's `git`, the `find`, the secret-injection setup script |
| `AgenticEventStreamAdapter.stream()` | the agent process itself |

Each produces a `SignalDeath` (`syn_shared.diagnostics`) carrying the signal
**name**, the failing **command**, and either the kernel ring-buffer lines
naming the faulting library or **the reason there are none**. It is logged at
`ERROR` and carried outward on `ExecutionResult.signal_death`, through
`FailedWorkspaceCommand`, into the message an operator reads.

The capture cannot raise. It runs on a path where a phase is already lost, and
a diagnostic that threw would turn one lost phase into an unreadable one.

## Reading the faulting library requires one deployment change

The kernel's account of a fault is the single fact worth having, and by default
**it is not reachable from inside the API container**. There is one ring buffer
per kernel and containers share the host's, but:

- `/dev/kmsg` is usually not present in a container at all, and
- reading it needs `CAP_SYSLOG` wherever `kernel.dmesg_restrict` is `1`
  (the default on Ubuntu).

So by default the diagnostic says the signal, the command, and *why the trace
is missing*. That distinction is deliberate: "nobody was permitted to look" is
a one-line configuration fix, and "the buffer was readable and held no fault
report" is **evidence** - a process killed by another process rather than by a
memory fault looks like the second.

To get traces, grant the service that runs workspaces read access to the ring
buffer:

```yaml
# the `api` service, in docker/docker-compose.yaml or an overlay
devices:
  - /dev/kmsg:/dev/kmsg:r
cap_add:
  - SYSLOG
```

This is **not enabled by default and should be a deliberate choice.**
`CAP_SYSLOG` lets the container read the host kernel log, which discloses
kernel addresses, and this is the service that holds the GitHub App private
key. Turn it on while investigating, then turn it off.

## What the next occurrence should settle

Collect the `SignalDeath` from a `-11` in each context - `git`, `find`, secret
injection, and a phase agent - and compare the library each names:

- **All name `cygrpc`** - the #1138 theory is right, this is one bug in
  `grpcio` forking out of a process with gRPC loaded, and the counter-evidence
  in #1295 needs explaining.
- **They name different libraries** - these are several bugs sharing an exit
  code, and #1295 should be split.

Neither was answerable before the capture existed. Both are cheap now.

## Not implemented here

A host-level `docker events --filter event=die` collector would see
container-level deaths that a process inside the stack cannot reach. It belongs
on the host, not in this repo, and is deliberately not built - noted so the gap
is visible rather than assumed covered.
