#!/usr/bin/env bash
# exp/skills-tmux-bridge v3 — uses `pkill` to terminate claude reliably
# between arms, removing the timing dependency that broke v2.

set -euo pipefail

EXP_ROOT="$(cd "$(dirname "$0")" && pwd)"
DRIVER="/home/ubuntu/Code/syntropic137/syntropic137_worktrees/20260610_skills/lib/agentic-primitives/providers/workspaces/interactive-tmux/driver/interactive_tmux.py"
PLUGIN_SRC="$EXP_ROOT/skill-plugin"
NAME="exp-skills-bridge-v3-$(date +%s)"
RUNS_DIR="$EXP_ROOT/runs-v3"
mkdir -p "$RUNS_DIR"

cleanup() {
    echo "[exp] cleanup: stopping workspace $NAME"
    python3 "$DRIVER" stop --name "$NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

WAIT_FOR_TUI_TIMEOUT=60

wait_for_claude_tui() {
    local container="$1"
    local label="$2"
    local i pane
    for i in $(seq 1 $WAIT_FOR_TUI_TIMEOUT); do
        pane=$(docker exec "$container" tmux capture-pane -t agents:0 -p 2>/dev/null || true)
        # New claude TUI is up when the splash banner appears AND prompt is ready
        if echo "$pane" | grep -q "Claude Code v" && echo "$pane" | grep -q "? for shortcuts"; then
            echo "[exp] $label: claude TUI ready after ${i}s"
            return 0
        fi
        sleep 1
    done
    echo "[exp] $label: WARN TUI not detected after ${WAIT_FOR_TUI_TIMEOUT}s"
    return 1
}

probe_and_capture() {
    local container="$1"
    local arm="$2"
    local out="$RUNS_DIR/$arm.txt"
    echo "[exp] $arm: send probe"
    docker exec "$container" tmux send-keys -t agents:0 -l \
        "Say the word READY in your reply."
    docker exec "$container" tmux send-keys -t agents:0 Enter
    # Wait for model to finish: look for the ● response marker AND empty prompt
    local i pane
    for i in $(seq 1 90); do
        pane=$(docker exec "$container" tmux capture-pane -t agents:0 -p 2>/dev/null || true)
        if echo "$pane" | grep -q "● " && ! echo "$pane" | grep -q "esc to interrupt"; then
            sleep 2
            break
        fi
        sleep 1
    done
    docker exec "$container" tmux capture-pane -t agents:0 -p -S -200 > "$out"
    if grep -qF "SYN_BRIDGE_OK_137" "$out"; then
        echo "[exp] $arm: ✓ SENTINEL PRESENT — skill ACTIVATED"
        return 0
    fi
    echo "[exp] $arm: ✗ SENTINEL ABSENT — skill NOT activated"
    return 1
}

kill_claude_then_relaunch() {
    local container="$1"
    local launch_cmd="$2"
    local label="$3"
    echo "[exp] $label: kill claude, relaunch with: $launch_cmd"
    docker exec "$container" pkill -KILL -f "^node.*claude" >/dev/null 2>&1 || true
    docker exec "$container" pkill -KILL claude >/dev/null 2>&1 || true
    sleep 3
    # Send a clearing Enter to make sure we're at a shell prompt
    docker exec "$container" tmux send-keys -t agents:0 C-c
    sleep 1
    docker exec "$container" tmux send-keys -t agents:0 "" Enter
    sleep 1
    # Launch new claude with the requested command
    docker exec "$container" tmux send-keys -t agents:0 -l "$launch_cmd"
    docker exec "$container" tmux send-keys -t agents:0 Enter
    wait_for_claude_tui "$container" "$label" || true
    sleep 2
}

# =============================================================================
# Boot a single workspace; reuse across all three arms via kill+relaunch.
# =============================================================================
echo "[exp] driver: $DRIVER"
echo "[exp] workspace: $NAME"
echo "[exp] runs dir: $RUNS_DIR"

echo
echo "[exp] === phase 0: start workspace ==="
python3 "$DRIVER" start --name "$NAME"
CONTAINER=$(docker ps --format '{{.Names}}' | grep -F "$NAME" | head -1)
echo "[exp] container: $CONTAINER"
wait_for_claude_tui "$CONTAINER" "phase0" || exit 1

# Pre-stage plugin + bridge files NOW so they're on disk for all arms.
# Each arm controls discovery via the claude command line OR config file
# present at relaunch time. The files staying on disk is fine — discovery
# is the variable, not file presence.
docker exec "$CONTAINER" mkdir -p /workspace/.syn-plugins /workspace/.claude
docker cp "$PLUGIN_SRC" "$CONTAINER:/workspace/.syn-plugins/sentinel-skill-plugin"
cat > /tmp/exp-bridge-settings-v3.json <<'JSON'
{
  "enabledPlugins": {
    "sentinel-skill-plugin@syn": true
  },
  "extraKnownPluginDirs": [
    "/workspace/.syn-plugins/sentinel-skill-plugin"
  ]
}
JSON
docker cp /tmp/exp-bridge-settings-v3.json "$CONTAINER:/workspace/.claude/settings.json"
echo "[exp] staged files:"
docker exec "$CONTAINER" find /workspace/.syn-plugins /workspace/.claude -maxdepth 4 -print

# -----------------------------------------------------------------------------
# Arm A: control — current claude (started by driver with no plugin flags)
#                  files exist on disk but settings.json was NOT present at
#                  claude startup; this isolates whether the running process
#                  picked up plugin discovery.
# -----------------------------------------------------------------------------
echo
echo "[exp] === ARM A: control (claude started before bridge files existed) ==="
ARM_A_PASS=0
if probe_and_capture "$CONTAINER" "A-control"; then ARM_A_PASS=1; fi

# -----------------------------------------------------------------------------
# Arm B: option-1 — kill claude, restart bare (so it reads
#                   <workspace>/.claude/settings.json from disk)
# -----------------------------------------------------------------------------
echo
echo "[exp] === ARM B: option-1 bridge (bare relaunch with settings.json on disk) ==="
kill_claude_then_relaunch "$CONTAINER" "claude" "B"
ARM_B_PASS=0
if probe_and_capture "$CONTAINER" "B-option1"; then ARM_B_PASS=1; fi

# -----------------------------------------------------------------------------
# Arm C: positive control — kill claude, restart with --plugin-dir
# -----------------------------------------------------------------------------
echo
echo "[exp] === ARM C: positive control (--plugin-dir flag) ==="
kill_claude_then_relaunch "$CONTAINER" \
    "claude --plugin-dir /workspace/.syn-plugins/sentinel-skill-plugin" "C"
ARM_C_PASS=0
if probe_and_capture "$CONTAINER" "C-plugindir"; then ARM_C_PASS=1; fi

# -----------------------------------------------------------------------------
echo
echo "============================================================"
echo " EXPERIMENT VERDICT (workspace: $NAME)"
echo "============================================================"
echo "  Arm A (control, claude started before files):    $([ $ARM_A_PASS -eq 1 ] && echo PRESENT || echo absent)"
echo "  Arm B (option-1: bare relaunch w/ settings.json): $([ $ARM_B_PASS -eq 1 ] && echo PRESENT || echo absent)"
echo "  Arm C (positive: relaunch w/ --plugin-dir flag):  $([ $ARM_C_PASS -eq 1 ] && echo PRESENT || echo absent)"
echo
echo "  Transcripts:"
echo "    $RUNS_DIR/A-control.txt"
echo "    $RUNS_DIR/B-option1.txt"
echo "    $RUNS_DIR/C-plugindir.txt"
echo

if [ $ARM_C_PASS -eq 1 ] && [ $ARM_B_PASS -eq 0 ]; then
    echo "  >>> DEFINITIVE: option-1 bridge insufficient."
    echo "  >>> --plugin-dir works; .claude/settings.json + .syn-plugins layout does NOT."
    echo "  >>> Durable bridge MUST be option 2 (upstream driver --plugin-dir support)."
elif [ $ARM_B_PASS -eq 1 ] && [ $ARM_C_PASS -eq 1 ]; then
    echo "  >>> BOTH BRIDGES WORK: option-1 sufficient + option-2 also works."
    echo "  >>> Recommend option 1 for simplicity (no upstream change)."
elif [ $ARM_C_PASS -eq 0 ]; then
    echo "  >>> INCONCLUSIVE: positive control failed; plugin/skill may be malformed"
    echo "  >>> for this image, or the description-match activation didn't fire."
fi
