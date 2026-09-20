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
die() { printf '\nPIT STOP ABORTED: %s\n' "$*" >&2; exit 1; }
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

pinned_tag() {  # the tag the compose FILE pins syn-api to (not the running container)
    remote "grep -oE 'syn-api:v[0-9][^[:space:]\"]*' $COMPOSE_DIR/$COMPOSE | head -1 | cut -d: -f2"
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

    step "build: syn-api + syn-gateway $TAG for linux/amd64"
    run docker buildx build --platform linux/amd64 --build-arg INCLUDE_DOCKER_CLI=1 \
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
    OLD="$(pinned_tag)"; [ -n "$OLD" ] || die "could not read the syn-api pin in the deployed compose file"
    echo "   compose pins: $OLD -> new: $TAG"
    if [ "$OLD" != "$TAG" ]; then
        run remote "cd $COMPOSE_DIR && cp $COMPOSE $COMPOSE.bak-$OLD && sed -i 's#syn-api:$OLD#syn-api:$TAG#; s#syn-gateway:$OLD#syn-gateway:$TAG#' $COMPOSE"
        # Two counts, not one: 0 old alone is also what a typo'd new tag gives;
        # 2 new alone is also what a no-op sed on an already-current file gives.
        if [ "$DRY" = 0 ]; then
            old_n="$(remote "grep -c 'syn-\(api\|gateway\):$OLD' $COMPOSE_DIR/$COMPOSE" || true)"
            new_n="$(remote "grep -c 'syn-\(api\|gateway\):$TAG' $COMPOSE_DIR/$COMPOSE" || true)"
            echo "   pins: old=$old_n (want 0) new=$new_n (want 2)"
            [ "$old_n" = 0 ] && [ "$new_n" = 2 ] || die "repoint did not change exactly the two pins"
        fi
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

step "swap: recreate api + gateway (no pull: the images are only in the host's daemon)"
# Re-checked immediately above; the swap runs in the same breath.
run remote "cd $COMPOSE_DIR && docker compose -f $COMPOSE up -d api gateway" | tail -4

step "verify: images, docker CLI, projections"
if [ "$DRY" = 0 ]; then
    # BY IMAGE ID, NOT BY TAG. `{{.Config.Image}}` reports the string the
    # container was created from, and a tag is mutable: a container built from
    # the PREVIOUS bytes behind this same tag prints exactly what a correct
    # deploy prints. The id is the thing that actually changed.
    for svc in api gateway; do
        want="$(remote "docker image inspect ghcr.io/syntropic137/syn-$svc:$TAG --format '{{.Id}}'")"
        got="$(remote "docker inspect syn137-$svc --format '{{.Image}}'")"
        up="$(remote "docker inspect syn137-$svc --format '{{.State.Running}}'")"
        printf '   syn137-%s: running=%s image=%s\n' "$svc" "$up" "$got"
        [ "$up" = true ] || die "syn137-$svc is not running after the swap"
        [ "$got" = "$want" ] || die "syn137-$svc is not running the image tagged $TAG (has $got, wanted $want)"
    done
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
fi
# AFTER verify, deliberately. Every stage above can `die`, and a deploy that
# failed should leave the new container refusing rather than admitting work to
# a version nobody has confirmed is healthy.
step "gate: resuming execution admission"
maintenance false "" || die "$TAG is live but admission is still paused; clear it with PUT /maintenance"

if [ "$DRY" = 1 ]; then
    step "DRY RUN DONE: nothing was built, shipped, staged or swapped. $TAG is NOT live."
else
    step "PIT STOP DONE: $TAG live in $(( $(date +%s) - T0 ))s. Last check is yours: dispatch one real workflow and watch a PHASE reach running."
fi
