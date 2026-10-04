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
set -euo pipefail

usage() { sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
[ $# -ge 1 ] || usage
VERSION="${1#v}"; shift
TAG="v${VERSION}"
REF="origin/main"
HOST="${SYN_PIT_HOST:-root@100.114.86.77}"
API="${SYN_PIT_API:-http://100.114.86.77:8137/api/v1}"
COMPOSE_DIR="/root/.syntropic137"
COMPOSE="docker-compose.syntropic137.yaml"
DRAIN_TIMEOUT="${SYN_PIT_DRAIN_TIMEOUT:-10800}"
API_READY_TIMEOUT="${SYN_PIT_API_READY_TIMEOUT:-900}"
MODE="all"; DRY=0; STAGE_ONLY=0; SWAP_ONLY=0
while [ $# -gt 0 ]; do
    case "$1" in
        --ref) [ $# -ge 2 ] || usage; REF="$2"; shift 2 ;;
        --stage-only) STAGE_ONLY=1; shift ;;
        --swap-only) SWAP_ONLY=1; shift ;;
        --dry-run) DRY=1; shift ;;
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
api() { curl -fsS -u "admin:${SYN_API_PASSWORD}" -m 90 "$API$1" -o "$2"; }

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

# Whether the READ PATH is at the head of the event store. Asked before any
# drain verdict is believed, and again after the swap: `status_counts` is
# tallied from an asynchronous projection, so a lagging one reports a quiet
# system while the event store knows about work it has not caught up to.
projections_healthy() {
    api "/health" "$TMP/health.json" 2>/dev/null || return 1
    python3 - "$TMP/health.json" <<'PY'
import json, sys
s = json.load(open(sys.argv[1])).get("subscription", {})
print("   subscription:", {k: s.get(k) for k in ("status", "is_catching_up", "lag")})
sys.exit(0 if s.get("status") == "healthy" and not s.get("is_catching_up") and not s.get("lag") else 1)
PY
}

# A drain is a statement about ONE instant: this returns 0 only when every
# status key present is terminal. Read from status_counts, which is tallied over
# the whole collection, never from a page of rows (see the runbook, section 1).
drained() {
    projections_healthy > /dev/null || { echo "   read path is not at the event-store head yet"; return 1; }
    api "/executions?page_size=1" "$TMP/counts.json" || return 1
    python3 - "$TMP/counts.json" <<'PY'
import json, sys
counts = json.load(open(sys.argv[1]))["status_counts"]
busy = sorted(set(counts) - {"completed", "failed", "cancelled", "interrupted"})
print(f"   status_counts: {counts}" + (f"  IN FLIGHT: {busy}" if busy else "  (drained)"))
sys.exit(1 if busy else 0)
PY
}

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
    curl -fsS -u "admin:${SYN_API_PASSWORD}" -m 30 -X PUT "$API/maintenance" \
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

step "drain: waiting for every execution to be terminal (timeout ${DRAIN_TIMEOUT}s)"
waited=0
until drained; do
    if [ "$waited" -ge "$DRAIN_TIMEOUT" ]; then
        # Nothing has been recreated yet, so the platform is exactly as it was
        # apart from the gate. Leaving it shut would strand admission on a
        # deploy that never happened.
        maintenance false "" || \
            echo "   WARNING: admission is still paused; clear it with PUT /maintenance" >&2
        die "not drained after ${DRAIN_TIMEOUT}s; nothing was recreated"
    fi
    sleep 60; waited=$((waited + 60))
done

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

if [ "$DRY" = 1 ]; then
    step "DRY RUN DONE: nothing was built, shipped, staged or swapped. $TAG is NOT live."
else
    step "PIT STOP DONE: $TAG live in $(( $(date +%s) - T0 ))s. Last check is yours: dispatch one real workflow and watch a PHASE reach running."
fi
