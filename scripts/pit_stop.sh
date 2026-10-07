#!/usr/bin/env bash
# Pit stop: put a beta on the selfhost VPS fast, with a hard gate at every stage.
# Called by: just pit-stop <version> [flags]
# Codifies docs/deployment/test-deploy.md (direct path, 3a). Not a release:
# no tag, no GitHub Release, no registry push, no npm publish.
#
# STAGE EARLY, SWAP LATE. Everything except the swap is safe while executions
# run, so it happens first. The drain gate is the only stage that waits, and
# the swap is one `compose up` after it. Recreating the API kills in-flight
# executions (#1381), which is why the drain is the speed limit. Admission is
# PAUSED for that whole window (#1387): draining alone only observes, so a
# webhook or a poller could admit work in the gap before the swap.
#
#   stages: prepare -> build -> ship -> stage | gate -> drain -> swap -> verify -> ungate
#   --stage-only  stop after `stage` (runs may still be in flight)
#   --swap-only   skip to `gate`; the version must already be staged
#   --dry-run     echo every mutating command; still run read-only checks
#   --skip-probe  EMERGENCIES ONLY: do not prove a real execution starts after ungate
set -euo pipefail

usage() { sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
[ $# -ge 1 ] || usage
VERSION="${1#v}"; shift
TAG="v${VERSION}"
REF="origin/main"
HOST="${SYN_PIT_HOST:-root@100.114.86.77}"
API="${SYN_PIT_API:-http://100.114.86.77:8137/api/v1}"
COMPOSE_DIR="/root/.syntropic137"
COMPOSE="docker-compose.syntropic137.yaml"
DRAIN_TIMEOUT="${SYN_PIT_DRAIN_TIMEOUT:-2700}"
API_READY_TIMEOUT="${SYN_PIT_API_READY_TIMEOUT:-900}"
PROBE_WORKFLOW="${SYN_PIT_PROBE_WORKFLOW:-telemetry-lag-probe-v1}"
PROBE_TIMEOUT="${SYN_PIT_PROBE_TIMEOUT:-600}"
PROBE_CANCEL_TIMEOUT="${SYN_PIT_PROBE_CANCEL_TIMEOUT:-300}"
MODE="all"; DRY=0; STAGE_ONLY=0; SWAP_ONLY=0; SKIP_PROBE=0
while [ $# -gt 0 ]; do
    case "$1" in
        --ref) [ $# -ge 2 ] || usage; REF="$2"; shift 2 ;;
        --stage-only) STAGE_ONLY=1; shift ;;
        --swap-only) SWAP_ONLY=1; shift ;;
        --dry-run) DRY=1; shift ;;
        --skip-probe) SKIP_PROBE=1; shift ;;
        *) usage ;;
    esac
done
: "${SYN_API_PASSWORD:?SYN_API_PASSWORD must be set (the drain gate and verify read the API)}"

# Worktrees live in a SIBLING directory, <repo>_worktrees/, never inside the
# repo. Resolve the repository from git's common dir so this works from any
# worktree and from a bare repository (which is how the maintainer clones it).
COMMON="$(git -C "$(dirname "$0")" rev-parse --path-format=absolute --git-common-dir)"
if [ "$(basename "$COMMON")" = ".git" ]; then REPO_TOP="$(dirname "$COMMON")"; else REPO_TOP="$COMMON"; fi
WT_BASE="$(dirname "$REPO_TOP")/$(basename "$REPO_TOP")_worktrees"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
T0=$(date +%s)
step() { printf '\n==> [%s +%ss] %s\n' "$(date -u +%H:%M:%SZ)" "$(( $(date +%s) - T0 ))" "$*"; }
# Once the swap has begun, an abort leaves the new containers half up and
# admission paused. Never silently: RECOVERY is set at the swap and every die
# from then on prints how to finish by hand (#1575).
RECOVERY=""
die() {
    printf '\nPIT STOP ABORTED: %s\n' "$*" >&2
    if [ -n "$RECOVERY" ]; then printf '%s\n' "$RECOVERY" >&2; fi
    exit 1
}
run() { if [ "$DRY" = 1 ]; then printf '   (dry-run) %s\n' "$*"; else "$@"; fi; }
remote() { ssh -o ConnectTimeout=15 "$HOST" "$@"; }
# Every request to the API goes through here. The credential travels as a curl
# config on stdin, never as an argument: `-u admin:<password>` sits in curl's
# argv, readable by any user on this machine through `ps` for the whole call
# (PC-85). Only the literal $SYN_API_PASSWORD in a PRINTED command remains.
# printf is a builtin, so the password is in no process's argv. A quoted config
# value treats \ and " as escapes, so both are escaped first.
api_curl() {
    # A line break would end the config line and curl echoes the rest of the
    # line in its parse error, i.e. the password reaches stderr. Refuse it
    # without ever printing the value.
    case "$SYN_API_PASSWORD" in
        *$'\n'*|*$'\r'*) die "SYN_API_PASSWORD contains a line break; refusing to pass it to curl (value not shown)" ;;
    esac
    local pw="${SYN_API_PASSWORD//\\/\\\\}"
    pw="${pw//\"/\\\"}"
    printf 'user = "admin:%s"\n' "$pw" | curl -K - -fsS "$@"
}
# $3, when given, caps the call below the default 90s (the probe's deadlines).
api() { api_curl -m "${3:-90}" "$API$1" -o "$2"; }

# DELIBERATELY NOT "last flag wins". `--stage-only --swap-only` would resolve
# to whichever came last, so an invocation that asked only to STAGE could
# drain and recreate production containers. Refuse the pair instead.
if [ "$STAGE_ONLY" = 1 ] && [ "$SWAP_ONLY" = 1 ]; then
    die "--stage-only and --swap-only are mutually exclusive"
fi
# `if`, not `[ ... ] && MODE=...`. Bash does not exit on the false test (the
# test is the left arm of an AND-list, which `set -e` exempts - verified), but
# the shape only stays safe while the assignment is the LAST thing on the line,
# and this is a file where a wrong `set -e` reading recreates containers.
if [ "$STAGE_ONLY" = 1 ]; then MODE="stage"; fi
if [ "$SWAP_ONLY" = 1 ]; then MODE="swap"; fi
# Everything below interpolates these into remote command strings and image
# references, so they are checked here rather than trusted there.
case "$VERSION" in
    [0-9]*) : ;;
    *) die "version must start with a digit (got: $VERSION)" ;;
esac
case "$VERSION" in
    *[!0-9A-Za-z.+-]*) die "version carries characters no image tag may: $VERSION" ;;
esac
case "$DRAIN_TIMEOUT" in
    ""|*[!0-9]*) die "SYN_PIT_DRAIN_TIMEOUT must be whole seconds (got: $DRAIN_TIMEOUT)" ;;
esac
case "$API_READY_TIMEOUT" in
    ""|*[!0-9]*) die "SYN_PIT_API_READY_TIMEOUT must be whole seconds (got: $API_READY_TIMEOUT)" ;;
esac
case "$PROBE_TIMEOUT" in
    ""|*[!0-9]*) die "SYN_PIT_PROBE_TIMEOUT must be whole seconds (got: $PROBE_TIMEOUT)" ;;
esac
case "$PROBE_CANCEL_TIMEOUT" in
    ""|*[!0-9]*) die "SYN_PIT_PROBE_CANCEL_TIMEOUT must be whole seconds (got: $PROBE_CANCEL_TIMEOUT)" ;;
esac
# Interpolated into an API path below, so checked here rather than trusted there.
case "$PROBE_WORKFLOW" in
    ""|*[!0-9A-Za-z._-]*) die "SYN_PIT_PROBE_WORKFLOW is not a workflow id (got: $PROBE_WORKFLOW)" ;;
esac

# Whether the READ PATH is at the head of the event store. Asked before any
# drain verdict is believed, and again after the swap: `status_counts` is
# tallied from an asynchronous projection, so a lagging one reports a quiet
# system while the event store knows about work it has not caught up to.
# Prints the status and /health's top-level degraded_reasons on every call.
# Returns 0 at the head, 1 not yet, 2 for `dropped_events`: a read model went
# past a start without applying it (#1696). That is wrong, not slow, and never
# heals by waiting (PC-115 waited 2.25h on it), so it gets its own code and the
# execution ids the repair runbook needs.
DROPPED_RUNBOOK="docs/runbooks/repair-dropped-execution-start.md"
projections_healthy() {
    api "/health" "$TMP/health.json" 2>/dev/null || { echo "   subscription: /health unreachable"; return 1; }
    python3 - "$TMP/health.json" <<'PY'
import json, sys
h = json.load(open(sys.argv[1]))
s = h.get("subscription") or {}
print("   subscription:", {k: s.get(k) for k in ("status", "is_catching_up", "lag")},
      "degraded_reasons:", h.get("degraded_reasons") or [])
if s.get("status") == "dropped_events":
    ids = sorted({u.get("execution_id") for u in s.get("unapplied_starts") or []} - {None})
    print("   DROPPED STARTS, never applied by the read path:", ids or "none named yet")
    sys.exit(2)
sys.exit(0 if s.get("status") == "healthy" and not s.get("is_catching_up") and not s.get("lag") else 1)
PY
}

# Free space on the data volume, as /health judges it (#1560). REPORTS, never
# gates: the thresholds and the refusal live in the API, so this only makes the
# number visible before a stage that loads images onto that disk, and again
# after the swap. A volume below the floor already refuses new executions.
disk_space() {
    api "/health" "$TMP/health.json" 2>/dev/null || { echo "   disk: /health unreachable"; return 0; }
    python3 - "$TMP/health.json" <<'DISK'
import json, sys
d = json.load(open(sys.argv[1])).get("disk")
if not d:
    print("   disk: not reported by this API (predates #1560)")
    sys.exit(0)
free = "unmeasurable" if d.get("free_percent") is None else f"{d['free_percent']:.1f}% free"
mark = "" if d.get("state") == "ok" else "  DEGRADED"
print(f"   disk: {d.get('path')} {free} state={d.get('state')} "
      f"(degraded below {d.get('degraded_below_percent')}%, "
      f"admission refused below {d.get('refuse_admission_below_percent')}%){mark}")
DISK
}

# A drain is a statement about ONE instant: this returns 0 only when every
# status key present is terminal. Read from status_counts, which is tallied over
# the whole collection, never from a page of rows (see the runbook, section 1).
# Returns 0 drained, 1 not yet, 2 the read path dropped events (see above).
drained() {
    local rc=0
    projections_healthy || rc=$?
    if [ "$rc" = 2 ]; then return 2; fi
    if [ "$rc" != 0 ]; then echo "   read path is not at the event-store head yet"; return 1; fi
    status_counts
}

# The busy-or-not reading of status_counts, printed; 0 only when every status
# key present is terminal. Also printed at the gate: queued vs running there is
# how long the drain is about to be.
status_counts() {
    api "/executions?page_size=1" "$TMP/counts.json" || return 1
    python3 - "$TMP/counts.json" <<'PY'
import json, sys
counts = json.load(open(sys.argv[1]))["status_counts"]
busy = sorted(set(counts) - {"completed", "failed", "cancelled", "interrupted"})
print(f"   queued={counts.get('queued', 0)} running={counts.get('running', 0)}  status_counts: {counts}"
      + (f"  IN FLIGHT: {busy}" if busy else "  (drained)"))
sys.exit(1 if busy else 0)
PY
}

# The drain's and the probe's bounds are DEADLINES on this monotonic clock,
# not counters of sleeps: a counter that adds 10 per poll let one slow GET after
# another stretch the probe's 600s bound past 90 minutes.
mono_now() { python3 -c 'import time; print(int(time.monotonic()))'; }

# Close or open the admission gate (#1387). THE DRAIN ALONE ONLY OBSERVES:
# `drained` is a statement about one instant, and nothing used to stop a
# webhook, a poller or an operator admitting work in the gap between that
# instant and the swap. This is what makes the drain a gate.
#
# The state is durable, so the container that comes up after the swap reads it
# and stays closed until `verify` passes. Clearing is therefore the LAST thing
# the deploy does, not something the swap does implicitly.
maintenance() {  # $1: true|false, $2: reason
    if [ "$DRY" = 1 ]; then printf '   (dry-run) PUT /maintenance active=%s\n' "$1"; return 0; fi
    api_curl -m 30 -X PUT "$API/maintenance" \
        -H 'Content-Type: application/json' \
        -d "{\"active\": $1, \"reason\": \"$2\", \"actor\": \"pit_stop.sh\"}" \
        -o "$TMP/maintenance.json" || return 1
    # Trust the RESPONSE, not the 200. The endpoint returns the state it
    # persisted, and a set call that did not persist is the window this whole
    # mechanism exists to close.
    python3 - "$TMP/maintenance.json" "$1" <<'GATE'
import json, sys
mode = json.load(open(sys.argv[1]))
print(f"   maintenance: active={mode['active']} reason={mode['reason']!r}")
sys.exit(0 if mode["active"] is (sys.argv[2] == "true") else 1)
GATE
}

# The executions still running, one per line, for an operator deciding what to
# do about them. Read-only: the pit stop never cancels anyone's work.
running_executions() {
    api "/executions?status=running&page_size=200" "$TMP/running.json" || { echo "   could not list the running executions"; return 0; }
    python3 - "$TMP/running.json" <<'RUN'
import json, sys
page = json.load(open(sys.argv[1]))
rows = page.get("executions") or []
print(f"   STILL RUNNING ({page.get('total', len(rows))}):")
for r in rows:
    print(f"     {r.get('workflow_execution_id')}  {r.get('workflow_name')}  started {r.get('started_at')}")
RUN
}

# A drain that cannot finish ends the pit stop, and RE-OPENS admission first.
# Nothing has been recreated, so the platform is exactly as it was apart from
# the gate, and a gate left shut with no pit stop running to clear it is what
# held admission for 2.25h in PC-115. Re-running with --swap-only closes it
# again in one step; the stage already on the host is untouched.
abort_drain() {
    if maintenance false ""; then
        echo "   admission is OPEN again" >&2
    else
        echo "   WARNING: admission is still PAUSED; clear it with PUT /maintenance" >&2
    fi
    die "$*; nothing was recreated"
}

# Wait, within SYN_PIT_DRAIN_TIMEOUT on a monotonic clock, for drained. Fails
# fast on dropped events (waiting cannot fix them); on an exhausted budget lists
# what is still running and stops, so the operator chooses (PC-114: one long
# repair round held a whole drain for ~2h).
drain_loop() {
    local deadline rc t
    deadline=$(( $(mono_now) + DRAIN_TIMEOUT ))
    while :; do
        rc=0
        drained || rc=$?
        if [ "$rc" = 0 ]; then return 0; fi
        if [ "$rc" = 2 ]; then
            abort_drain "the read path DROPPED execution starts (subscription.status=dropped_events, #1696). Waiting cannot fix it. Repair the executions named above with $DROPPED_RUNBOOK, then re-run with --swap-only"
        fi
        t=$(( deadline - $(mono_now) ))
        if [ "$t" -le 0 ]; then
            running_executions
            abort_drain "drain budget of ${DRAIN_TIMEOUT}s spent with executions still in flight (listed above); none was cancelled. Choose: WAIT (re-run with --swap-only; SYN_PIT_DRAIN_TIMEOUT sets the budget), or INTERRUPT them yourself, re-run, and resume them after the pit stop"
        fi
        if [ "$t" -gt 60 ]; then t=60; fi
        sleep "$t"
    done
}

# The probe's workflow is installed and ACTIVE, asked before anything is built
# (PC-87). beta.11 built, shipped, gated, drained for 40 minutes, swapped and
# verified, and only then was refused at dispatch: "Workflow
# telemetry-lag-probe-v1 is archived and cannot launch executions". Read-only:
# it touches neither the deployment nor the admission gate.
#
# Through the LIST, not GET /workflows/{id}: only the list's summary carries
# is_archived, and `search` matches ids by substring, so the id is matched
# exactly here. It does not install the workflow itself: reinstalling is what
# reactivates an archived template, which would quietly undo an archive someone
# made on purpose, and the `syn` CLI it needs is not otherwise a dependency.
probe_workflow_ready() {
    api "/workflows?search=$PROBE_WORKFLOW&include_archived=true&page_size=100" "$TMP/probe_workflow.json" \
        || die "could not read the probe workflow $PROBE_WORKFLOW from $API/workflows. Nothing was built or gated."
    local verdict
    verdict="$(python3 - "$TMP/probe_workflow.json" "$PROBE_WORKFLOW" <<'WF'
import json, sys
found = [w for w in json.load(open(sys.argv[1]))["workflows"] if w.get("id") == sys.argv[2]]
print("missing" if not found else "archived" if found[0].get("is_archived") else "active")
WF
)" || die "could not read the probe workflow $PROBE_WORKFLOW from $API/workflows. Nothing was built or gated."
    echo "   probe workflow $PROBE_WORKFLOW: $verdict"
    if [ "$verdict" != active ]; then
        die "the probe workflow $PROBE_WORKFLOW is $verdict on $API, so the probe after the swap could not launch. Nothing was built or gated. Install it (an install also reactivates an archived one):
   SYN_API_URL=$API SYN_API_USER=admin SYN_API_PASSWORD=\$SYN_API_PASSWORD syn workflow install workflows/probes/telemetry-lag
or, in an emergency only, re-run with --skip-probe."
    fi
}

# Only when this run will dispatch the probe: --stage-only never does.
if [ "$SKIP_PROBE" = 0 ] && [ "$MODE" != "stage" ]; then
    step "precheck: the probe workflow $PROBE_WORKFLOW is installed and active"
    probe_workflow_ready
fi

step "precheck: free space on the data volume"
disk_space

if [ "$MODE" != "swap" ]; then
    step "prepare: worktree at $REF, bump to $VERSION"
    WT="$WT_BASE/pit-stop-$VERSION"
    [ -e "$WT" ] && die "$WT already exists; remove it or pick another version"
    run git -C "$REPO_TOP" fetch -q origin
    run git -C "$REPO_TOP" worktree add -b "chore/bump-$VERSION" "$WT" "$REF"
    if [ "$DRY" = 0 ]; then
        git -C "$WT" submodule update --init --recursive --quiet
        (cd "$WT" && just bump-version "$VERSION") | tail -1 | grep -q "^OK: all" || die "bump-version did not report OK"
        ! git -C "$WT" status --porcelain | grep -q '^??' || die "bump left untracked files"
        git -C "$WT" status --porcelain | awk '$1=="M"{print $2}' | (cd "$WT" && xargs git add --)
        git -C "$WT" commit --no-verify -q -m "chore: bump to $VERSION" && echo "   committed $(git -C "$WT" rev-parse --short HEAD)"
    fi
    # The commit the image is built from is the BUMP commit, never $REF:
    # bump-version rewrites the package metadata syn-api reads its release from,
    # so $REF's tree is not the tree that ships (#1473). chore/bump-$VERSION is
    # never pushed, so this SHA resolves in this repository, not on GitHub. That
    # is also what tells a pit stop apart from a release of the same tag.
    if [ "$DRY" = 0 ]; then
        BUILT_SHA="$(git -C "$WT" rev-parse --verify HEAD)"
    else
        BUILT_SHA="<the bump commit on $REF>"
    fi

    step "build: syn-api + syn-gateway $TAG for linux/amd64 (commit $BUILT_SHA)"
    # SYN_BUILD_* are what /version reports as image_tag and commit, and verify
    # reads them back below. The fitness test in
    # ci/fitness/infrastructure/test_release_build_args.py fails if they go.
    run docker buildx build --platform linux/amd64 --build-arg INCLUDE_DOCKER_CLI=1 \
        --build-arg SYN_BUILD_IMAGE_TAG="$TAG" --build-arg SYN_BUILD_COMMIT="$BUILT_SHA" \
        -t "ghcr.io/syntropic137/syn-api:$TAG" --load -f "$WT/infra/docker/images/syn-api/Dockerfile" "$WT"
    run docker buildx build --platform linux/amd64 \
        -t "ghcr.io/syntropic137/syn-gateway:$TAG" --load -f "$WT/infra/docker/images/gateway/Dockerfile" "$WT"
    # The #1216 trap: /health stays green while every execution fails at bootstrap.
    [ "$DRY" = 1 ] || (cd "$WT" && just verify-image-capabilities syn-api "ghcr.io/syntropic137/syn-api:$TAG")

    step "ship: docker save | docker load on $HOST"
    if [ "$DRY" = 0 ]; then
        docker save "ghcr.io/syntropic137/syn-api:$TAG" "ghcr.io/syntropic137/syn-gateway:$TAG" | remote 'docker load' | tail -2
    else
        printf '   (dry-run) docker save ... | ssh %s docker load\n' "$HOST"
    fi
    [ "$DRY" = 1 ] || [ "$(remote "docker images --format '{{.Repository}}:{{.Tag}}' | grep -c ':$TAG\$'")" = 2 ] \
        || die "expected TWO images tagged $TAG on the host; the deploy would be half old"

    step "stage: back up the deployed compose and repoint both pins"
    # Read here, repointed locally, written back whole: a release-installed host
    # pins each image by its own digest and a hotfixed one by its own tag, so no
    # single substitution covers both services (scripts/pit_stop_repoint.py).
    remote "cat $COMPOSE_DIR/$COMPOSE" > "$TMP/compose.deployed" || die "could not read the deployed compose file"
    BAK="$(python3 "$(dirname "$0")/pit_stop_repoint.py" "$TAG" "$TMP/compose.deployed" "$TMP/compose.staged")" \
        || die "could not repoint the syn-api/syn-gateway pins in the deployed compose file"
    if [ -n "$BAK" ]; then
        # Written beside the file, checked against the staged checksum, and only
        # then renamed over it. `cat` exits 0 on a short read, so without the
        # check a dropped transfer would install half a compose file.
        SUM="$(python3 -c 'import hashlib, sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$TMP/compose.staged")"
        run remote "cd $COMPOSE_DIR && cat > $COMPOSE.pit-stop && echo '$SUM  $COMPOSE.pit-stop' | sha256sum -c --status - && cp $COMPOSE $COMPOSE.bak-$BAK && mv $COMPOSE.pit-stop $COMPOSE || { rm -f $COMPOSE.pit-stop; exit 1; }" < "$TMP/compose.staged" \
            || die "the staged compose did not arrive intact on $HOST; the deployed file is unchanged"
        if [ "$DRY" = 0 ]; then
            remote "cat $COMPOSE_DIR/$COMPOSE" | cmp -s - "$TMP/compose.staged" || die "the compose on $HOST is not the one staged; the backup is $COMPOSE.bak-$BAK"
            echo "   backed up to $COMPOSE.bak-$BAK"
        fi
    else
        echo "   both pins are already $TAG"
    fi
    # The same count --swap-only prechecks, so a stage it would refuse fails here.
    if [ "$DRY" = 0 ]; then
        new_n="$(remote "grep -c 'syn-\(api\|gateway\):$TAG' $COMPOSE_DIR/$COMPOSE" || true)"
        [ "$new_n" = 2 ] || die "the deployed compose pins $new_n/2 services to $TAG after the repoint"
    fi
    if [ "$MODE" = "stage" ]; then
        step "staged $TAG; run with --swap-only once drained"
        exit 0
    fi
fi

if [ "$MODE" = "swap" ] && [ "$DRY" = 0 ]; then
    step "precheck: $TAG is staged in the compose file and present on the host"
    # --swap-only recreates whatever the compose file names. Without this it
    # would drain the platform and disrupt production containers before
    # discovering, at verify, that the file pins something else entirely.
    pins="$(remote "grep -c 'syn-\(api\|gateway\):$TAG' $COMPOSE_DIR/$COMPOSE" || true)"
    [ "$pins" = 2 ] || die "the deployed compose file pins $pins/2 services to $TAG; stage it first"
    staged="$(remote "docker images --format '{{.Repository}}:{{.Tag}}' | grep -c ':$TAG\$'" || true)"
    [ "$staged" = 2 ] || die "$staged/2 images tagged $TAG on $HOST; stage it first"
    echo "   pins=2 images=2"
fi

step "gate: pausing execution admission for the rest of the pit stop"
maintenance true "pit stop $VERSION" || die "could not pause admission; nothing was recreated"
status_counts || true

step "drain: waiting for every execution to be terminal (budget ${DRAIN_TIMEOUT}s)"
drain_loop

# Bring api + gateway up. Idempotent: a second call recreates nothing that
# already matches the compose file, it only starts what is still `Created`.
swap_up() { run remote "cd $COMPOSE_DIR && docker compose -f $COMPOSE up -d api gateway" 2>&1 | tail -4; }

# Wait, bounded, for the API CONTAINER to pass its health check. That check is
# liveness: /health answers 200 "starting" while a long startup migration runs
# (#1575), so this normally returns within one health interval. A restart count
# that moves is a crash loop, not a slow start, and is not waited out.
wait_for_api_healthy() {
    local waited=0 status restarts health restarts0=""
    while :; do
        read -r status restarts health <<<"$(remote "docker inspect syn137-api --format '{{.State.Status}} {{.RestartCount}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}'" || echo "missing - -")"
        printf '   [+%ss] syn137-api: status=%s restarts=%s health=%s\n' "$waited" "$status" "$restarts" "$health"
        [ "$health" = healthy ] && return 0
        [ -n "$restarts0" ] || restarts0="$restarts"
        if [ "$restarts" != "$restarts0" ]; then echo "   syn137-api restarted while waiting: a crash loop, not a slow start"; return 1; fi
        [ "$waited" -ge "$API_READY_TIMEOUT" ] && return 1
        sleep 15; waited=$((waited + 15))
    done
}

# Wait, bounded, for the API to be READY: /health says "healthy", not
# "starting". Liveness got the gateway started; this is what admission waits on.
wait_for_api_ready() {
    local waited=0
    until api "/health" "$TMP/ready.json" 2>/dev/null \
        && python3 -c 'import json, sys; s = json.load(open(sys.argv[1]))["status"]; print("   /health status:", s); sys.exit(s != "healthy")' "$TMP/ready.json"; do
        [ "$waited" -ge "$API_READY_TIMEOUT" ] && return 1
        printf '   [+%ss] API not ready yet (a startup migration may still be running)\n' "$waited"
        sleep 15; waited=$((waited + 15))
    done
}

step "swap: recreate api + gateway (no pull: the images are only in the host's daemon)"
RECOVERY="RECOVERY: admission is still PAUSED. Once syn137-api is healthy, finish by hand:
   ssh $HOST 'cd $COMPOSE_DIR && docker compose -f $COMPOSE up -d gateway'
   curl -fsS -u admin:\$SYN_API_PASSWORD $API/version     # image_tag must be $TAG
   curl -fsS -u admin:\$SYN_API_PASSWORD -X PUT $API/maintenance -H 'Content-Type: application/json' -d '{\"active\": false, \"reason\": \"\", \"actor\": \"manual\"}'"
# Re-checked immediately above; the swap runs in the same breath.
if ! swap_up; then
    # The usual cause: the gateway waits on `api: service_healthy` and the API
    # took longer than its health window. Wait for it, then start what compose
    # left behind. Anything else fails the wait and stops here, loudly.
    step "swap: compose up failed; waiting up to ${API_READY_TIMEOUT}s for syn137-api to report healthy"
    [ "$DRY" = 1 ] || wait_for_api_healthy || die "syn137-api did not become healthy within ${API_READY_TIMEOUT}s"
    step "swap: syn137-api is healthy; re-running compose up for its dependents"
    swap_up || die "compose up failed again after syn137-api reported healthy"
fi

step "verify: images, docker CLI, projections, build identity"
if [ "$DRY" = 0 ]; then
    # BY IMAGE ID, NOT BY TAG. `{{.Config.Image}}` reports the string the
    # container was created from, and a tag is mutable: a container built from
    # the PREVIOUS bytes behind this same tag prints exactly what a correct
    # deploy prints. The id is the thing that actually changed.
    #
    # Every read guarded with `|| die`: under `set -e` a failed assignment exits
    # on the spot, skipping die() and the RECOVERY it prints while admission is
    # paused. An unreachable host is exactly when the operator needs it (#1575).
    for svc in api gateway; do
        want="$(remote "docker image inspect ghcr.io/syntropic137/syn-$svc:$TAG --format '{{.Id}}'")" \
            || die "could not read the id of image syn-$svc:$TAG on $HOST"
        got="$(remote "docker inspect syn137-$svc --format '{{.Image}}'")" \
            || die "could not inspect syn137-$svc on $HOST"
        up="$(remote "docker inspect syn137-$svc --format '{{.State.Running}}'")" \
            || die "could not inspect syn137-$svc on $HOST"
        printf '   syn137-%s: running=%s image=%s\n' "$svc" "$up" "$got"
        [ "$up" = true ] || die "syn137-$svc is not running after the swap"
        [ "$got" = "$want" ] || die "syn137-$svc is not running the image tagged $TAG (has $got, wanted $want)"
    done
    wait_for_api_ready || die "the API did not finish starting within ${API_READY_TIMEOUT}s"
    remote "docker exec syn137-api sh -c 'command -v docker'" >/dev/null || die "no docker CLI in syn-api (#1216): every execution will fail at bootstrap"
    # A `for` loop reports its LAST command, which here is `sleep`. Written as
    # `for ...; done || die`, every attempt could fail and the script would
    # still print DONE. The flag is what makes that failure reachable.
    healthy=0
    for _ in $(seq 1 30); do
        if projections_healthy; then healthy=1; break; fi
        sleep 10
    done
    [ "$healthy" = 1 ] || die "projections not healthy after the swap"
    disk_space
    # The image id above proves the right bytes are running; this proves they
    # say so. Under --swap-only this run built nothing, so the commit is only
    # required to be present, not to equal one.
    api "/version" "$TMP/version.json" || die "GET /version failed after the swap"
    python3 - "$TMP/version.json" "$TAG" "${BUILT_SHA:-}" <<'PY' || die "the running API does not report the build just shipped (want image_tag=$TAG commit=${BUILT_SHA:-any})"
import json, sys
build, tag, sha = json.load(open(sys.argv[1])), sys.argv[2], sys.argv[3]
print(f"   /version: image_tag={build.get('image_tag')} commit={build.get('commit')}")
commit_ok = build.get("commit") == sha if sha else bool(build.get("commit"))
sys.exit(0 if build.get("image_tag") == tag and commit_ok else 1)
PY
fi
# AFTER verify, deliberately. Every stage above can `die`, and a deploy that
# failed should leave the new container refusing rather than admitting work to
# a version nobody has confirmed is healthy.
step "gate: resuming execution admission"
maintenance false "" || die "$TAG is live but the clear did not complete; retry PUT /maintenance (a 503 means admission is open but the paused triggers were not woken, #1387)"

# THE START PATH, PROVEN (#1641). Every check above passed on beta.8 and beta.9
# while no execution could start: each direct start was dropped as a duplicate,
# and beta.8 sat live and broken for ~3h because the last check was manual. So
# the pit stop dispatches one real run and declares nothing until a PHASE of it
# is seen `running`. AFTER the ungate, deliberately: the probe goes through the
# same admission as everyone else's work, and a failed probe never re-closes it.
api_post() { api_curl -m "${4:-90}" -X POST "$API$1" -H 'Content-Type: application/json' -d "$2" -o "$3"; }

# Every probe HTTP call is capped to what is left of its deadline.
left() {  # $1: deadline from mono_now; seconds left, at most 90, 0 once passed
    local l=$(( $1 - $(mono_now) ))
    if [ "$l" -gt 90 ]; then l=90; fi
    if [ "$l" -lt 0 ]; then l=0; fi
    echo "$l"
}
nap() {  # $1: deadline; sleep the poll interval, never past the deadline
    local t
    t="$(left "$1")"
    if [ "$t" -gt 10 ]; then t=10; fi
    if [ "$t" -gt 0 ]; then sleep "$t"; fi
}

# THE one reading of GET /executions/{id} for the probe; the wait and the
# settle below both act on it, so they cannot disagree about what a status
# means. Prints a status line and returns:
#   0 STARTED   a phase is running or completed, and the run is still live
#   1 PENDING   queued, starting, or a phase not yet running
#   2 FAILED    the run failed or was interrupted - at ANY point, including
#               after a phase ran: that is not a clean stop. TERMINAL.
#   3 ENDED     completed or cancelled AFTER a phase ran or completed. TERMINAL.
#   4 STOPPED   completed or cancelled with no phase ever running, which is
#               also how a queued start that was withdrawn reads (#1650). TERMINAL.
#   5 FAILING   a phase failed, but the run itself is not terminal yet
probe_classify() {
    python3 - "$1" <<'PROBE'
import json, sys
d = json.load(open(sys.argv[1]))
phases = [f"{p.get('phase_id')}={p.get('status')}" for p in d.get("phases") or []]
print(f"status={d.get('status')} phases=[{', '.join(phases)}]")
statuses = [p.get("status") for p in d.get("phases") or []]
started = any(s in ("running", "completed") for s in statuses)
if d.get("status") in ("failed", "interrupted"):
    sys.exit(2)
if d.get("status") in ("completed", "cancelled"):
    sys.exit(3 if started else 4)
if "failed" in statuses:
    sys.exit(5)
sys.exit(0 if started else 1)
PROBE
}

# One read of the probe: sets PROBE_CLASS (as above, or 1 when the GET itself
# failed, which is what a start dropped before it existed looks like) and
# PROBE_LAST, which says which of the two it was.
probe_read() {  # $1: execution id, $2: deadline
    local t
    PROBE_CLASS=1
    # Set before the deadline check: a deadline already passed when this is
    # first called (a slow host) must still leave PROBE_LAST set, or every
    # message naming it dies on `set -u` instead of reporting the probe.
    PROBE_LAST="${PROBE_LAST:-no status read before the deadline}"
    t="$(left "$2")"; [ "$t" -gt 0 ] || return 0
    if api "/executions/$1" "$TMP/probe_detail.json" "$t" 2>/dev/null; then
        if PROBE_LAST="$(probe_classify "$TMP/probe_detail.json")"; then PROBE_CLASS=0; else PROBE_CLASS=$?; fi
    else
        PROBE_LAST="not found by GET /executions/$1, or no answer in time (a start dropped before it existed looks exactly like this)"
    fi
}

# Leave the probe TERMINAL, and say so only once GET has SHOWN it terminal: a
# probe still in flight is in-flight work to the next pit stop's drain, which
# would wait on it. An accepted cancel is not proof - it is read back. Since
# #1650 the cancel withdraws a start still queued for capacity, so a probe
# that never started is stopped too. The cancel is re-sent on every read that
# is not terminal: a withdrawal that loses the race with its own start
# (#1650's known limit) leaves a live run that only a later cancel stops.
# Returns 0 once GET shows completed/cancelled, 2 once it shows failed or
# interrupted, 1 when the deadline passed with no terminal status SEEN.
probe_settle() {  # $1: execution id
    local deadline t
    deadline=$(( $(mono_now) + PROBE_CANCEL_TIMEOUT ))
    while :; do
        probe_read "$1" "$deadline"
        printf '   probe %s: %s\n' "$1" "$PROBE_LAST"
        case "$PROBE_CLASS" in
            3|4) return 0 ;;
            2) return 2 ;;
        esac
        t="$(left "$deadline")"
        [ "$t" -gt 0 ] || return 1
        api_post "/executions/$1/cancel" '{"reason": "pit stop probe: stopping it before the pit stop exits"}' "$TMP/probe_cancel.json" "$t" 2>/dev/null \
            || echo "   cancel not accepted; reading it back"
        nap "$deadline"
    done
}

# A probe that may still be live is never left without the exact command that
# stops it. $SYN_API_PASSWORD stays a literal here: it is for the operator's
# shell to expand, and is never expanded into a log.
probe_cleanup() {  # $1: execution id
    # shellcheck disable=SC2016  # the literal $SYN_API_PASSWORD is the point
    printf 'curl -fsS -u "admin:$SYN_API_PASSWORD" -X POST %s/executions/%s/cancel' "$API" "$1"
}

# The pit stop has failed because of the probe. Settle it first, so the next
# drain does not wait on it, then die. When the settle could not SEE it
# terminal, the failure says it is still live and how to stop it.
probe_abort() {  # $1: why
    local settled=0
    probe_settle "$PROBE_ID" || settled=$?
    if [ "$settled" = 1 ]; then
        die "$1
PROBE $PROBE_ID MAY STILL BE LIVE: not seen terminal within ${PROBE_CANCEL_TIMEOUT}s of cancelling (last: $PROBE_LAST). The next pit stop's drain will wait on it. Stop it, then check GET /executions/$PROBE_ID shows cancelled:
   $(probe_cleanup "$PROBE_ID")"
    fi
    die "$1
Probe $PROBE_ID is terminal, verified by GET: $PROBE_LAST"
}

PROBE_LINE=""
if [ "$DRY" = 1 ]; then
    printf '   (dry-run) POST /workflows/%s/execute, then wait for a phase to reach running\n' "$PROBE_WORKFLOW"
elif [ "$SKIP_PROBE" = 1 ]; then
    printf '\n!!! --skip-probe: NO EXECUTION HAS BEEN SEEN TO START ON %s.\n!!! beta.8 passed every other check with every start dropped (#1641).\n!!! Dispatch one real workflow now and watch a PHASE reach running.\n' "$TAG" >&2
    PROBE_LINE=" PROBE SKIPPED: dispatch one real workflow and watch a PHASE reach running."
else
    # BAK is set only when this run repointed the pins; under --swap-only the
    # backup is the $COMPOSE.bak-* an earlier stage left on the host: put its PIN in.
    rollback="ssh $HOST 'cd $COMPOSE_DIR && ls $COMPOSE.bak-* && cp $COMPOSE.bak-${BAK:-PIN} $COMPOSE'
   ssh $HOST 'cd $COMPOSE_DIR && docker compose -f $COMPOSE up -d api gateway'"
    RECOVERY="$TAG is LIVE and admission is OPEN, deliberately: in-flight work from other users is not held hostage to a failed probe. Nothing was rolled back. To roll back by hand:
   $rollback"
    step "probe: dispatching $PROBE_WORKFLOW; waiting up to ${PROBE_TIMEOUT}s for a PHASE to reach running"
    probe_deadline=$(( $(mono_now) + PROBE_TIMEOUT ))
    api_post "/workflows/$PROBE_WORKFLOW/execute" \
        "{\"task\": \"pit stop $TAG start-path probe: cancelled once a phase is running\", \"tags\": [\"pit-stop-probe\"], \"no_eval\": true}" \
        "$TMP/probe.json" "$(left "$probe_deadline")" \
        || die "could not dispatch the probe $PROBE_WORKFLOW (not installed on this host? syn workflow install workflows/probes/telemetry-lag)"
    PROBE_ID="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["execution_id"])' "$TMP/probe.json")" \
        || die "the probe dispatch answered without an execution_id"
    RECOVERY="$RECOVERY
Inspect the probe: curl -fsS -u admin:\$SYN_API_PASSWORD $API/executions/$PROBE_ID"
    while :; do
        probe_read "$PROBE_ID" "$probe_deadline"
        printf '   probe %s: %s\n' "$PROBE_ID" "$PROBE_LAST"
        case "$PROBE_CLASS" in
            0|3) break ;;
            2|4|5) probe_abort "probe $PROBE_ID ended without a phase reaching running. Last status: $PROBE_LAST" ;;
        esac
        if [ "$(left "$probe_deadline")" = 0 ]; then
            # Withdrawn or cancelled and SEEN terminal, so the next drain does
            # not wait on it; a FAILURE either way, because it never ran.
            probe_abort "probe $PROBE_ID did not reach a running phase within ${PROBE_TIMEOUT}s. Last status: $PROBE_LAST"
        fi
        nap "$probe_deadline"
    done
    # Not token-free: this is a real agent on a real model, so it is stopped as
    # soon as it has proven the start, and the stop is read back, not assumed.
    if [ "$PROBE_CLASS" = 0 ]; then
        step "probe: a phase is running; cancelling $PROBE_ID"
        settled=0; probe_settle "$PROBE_ID" || settled=$?
        if [ "$settled" = 2 ]; then
            die "probe $PROBE_ID FAILED after a phase ran: the run did not stop cleanly. Last status: $PROBE_LAST"
        fi
        [ "$settled" = 0 ] \
            || die "the start path works, but probe $PROBE_ID is not terminal after ${PROBE_CANCEL_TIMEOUT}s (last: $PROBE_LAST). PROBE $PROBE_ID MAY STILL BE LIVE, and the next pit stop's drain will wait on it. Stop it, then check GET /executions/$PROBE_ID shows cancelled:
   $(probe_cleanup "$PROBE_ID")"
    fi
    PROBE_LINE=" Probe $PROBE_ID reached a running phase and was stopped (terminal, verified by GET)."
fi

if [ "$DRY" = 1 ]; then
    step "DRY RUN DONE: nothing was built, shipped, staged or swapped. $TAG is NOT live."
else
    step "PIT STOP DONE: $TAG live in $(( $(date +%s) - T0 ))s.$PROBE_LINE"
fi
