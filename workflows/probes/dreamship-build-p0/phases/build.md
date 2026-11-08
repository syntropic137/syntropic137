# DreamShip P0 build probe (okrs-51p.30)

$ARGUMENTS

You are a measurement probe. Follow these steps exactly, in order, and do
nothing else. Do not fix, retry, or work around a failure: a failure is the
result being measured. Run each block as ONE Bash call.

## 1. Start the build detached

```
cd /workspace/repos/* && pwd && git rev-parse HEAD
echo "TMPDIR as received: ${TMPDIR:-<unset>}"
mkdir -p /workspace/probe
cat > /workspace/probe/run.sh <<'SH'
set -u
# The platform sets TMPDIR=/workspace/.tmp (exec-capable; /tmp is noexec).
# The fallback only matters on a deployment that predates that (#1100).
export TMPDIR="${TMPDIR:-/workspace/.tmp}"
mkdir -p "$TMPDIR"
cd /workspace/repos/*
date -u +%s > /workspace/probe/start
{
  rustup show active-toolchain &&
  cargo check --locked -p dream-ship-engine --lib &&
  cargo build --manifest-path ws_apps/dream-ship-engine/Cargo.toml --target wasm32-unknown-unknown
} > /workspace/probe/build.log 2>&1
echo $? > /workspace/probe/exit
date -u +%s > /workspace/probe/end
SH
nohup bash /workspace/probe/run.sh > /dev/null 2>&1 &
echo STARTED
nproc; free -m 2>/dev/null || true
cat /sys/fs/cgroup/memory.max 2>/dev/null || cat /sys/fs/cgroup/memory/memory.limit_in_bytes 2>/dev/null || echo "memory.max unreadable"
df -h /workspace
```

`rustup show active-toolchain` installs the pinned nightly and the wasm32
target from the repo's rust-toolchain.toml on first use. That is part of the
cold cost being measured.

## 2. Poll until it finishes

Repeat this as separate Bash calls until it prints `DONE`. Do not shorten the
sleep and do not stop early. Stop polling if the phase is about to time out.

```
sleep 540; if [ -f /workspace/probe/exit ]; then echo DONE; else echo RUNNING; tail -n 3 /workspace/probe/build.log; fi
```

## 3. Collect evidence

```
cd /workspace/repos/*
echo "EXIT=$(cat /workspace/probe/exit 2>/dev/null || echo none)"
echo "WALL_SECONDS=$(( $(cat /workspace/probe/end 2>/dev/null || date -u +%s) - $(cat /workspace/probe/start) ))"
echo "PEAK_MEM_BYTES=$(cat /sys/fs/cgroup/memory.peak 2>/dev/null || cat /sys/fs/cgroup/memory/memory.max_usage_in_bytes 2>/dev/null || echo unreadable)"
echo "OOM_EVENTS=$(grep -E '^oom_kill ' /sys/fs/cgroup/memory.events 2>/dev/null || echo unreadable)"
echo "TARGET_SIZE=$(du -sh target 2>/dev/null | cut -f1)"
echo "TOOLCHAIN_SIZE=$(du -sh "${RUSTUP_HOME:-$HOME/.rustup}" 2>/dev/null | cut -f1)"
echo "CARGO_HOME_SIZE=$(du -sh "${CARGO_HOME:-$HOME/.cargo}" 2>/dev/null | cut -f1)"
df -h /workspace | tail -1
tail -n 40 /workspace/probe/build.log
```

## 4. Report

Write `artifacts/output/build.md` with exactly these lines (values from step
3, `unknown` if missing), then the last 40 log lines in a fenced block, then
print the file:

```
COMMIT: <sha from step 1>
CPUS: <nproc>
MEMORY_LIMIT: <memory.max from step 1>
EXIT: <exit code, or none if the build never finished>
WALL_SECONDS: <n>
PEAK_MEM_BYTES: <n>
OOM_EVENTS: <line>
TARGET_SIZE: <size>
TOOLCHAIN_SIZE: <size>
CARGO_HOME_SIZE: <size>
VERDICT: <PASS if EXIT is 0, else FAIL>
```
