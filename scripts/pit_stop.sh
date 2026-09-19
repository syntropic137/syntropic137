#!/usr/bin/env bash
# Pit stop: put a beta on the selfhost VPS fast, with a hard gate at every stage.
# Called by: just pit-stop <version> [flags]
# Codifies docs/deployment/test-deploy.md (direct path, 3a). Not a release:
# no tag, no GitHub Release, no registry push, no npm publish.
#
# STAGE EARLY, SWAP LATE. Everything except the swap is safe while executions
# run, so it happens first. The drain gate is the only stage that waits, and
# the swap is one `compose up` after it. Recreating the API kills in-flight
# executions (#1381), which is why the drain is the speed limit.
#
#   stages: prepare -> build -> ship -> stage | drain -> swap -> verify
#   --stage-only  stop after `stage` (runs may still be in flight)
#   --swap-only   skip to `drain`; the version must already be staged
#   --dry-run     echo every mutating command; still run read-only checks
set -euo pipefail

usage() { sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
[ $# -ge 1 ] || usage
VERSION="${1#v}"; shift
TAG="v${VERSION}"
REF="origin/main"
HOST="${SYN_PIT_HOST:-root@100.114.86.77}"
API="${SYN_PIT_API:-http://100.114.86.77:8137/api/v1}"
COMPOSE_DIR="/root/.syntropic137"
COMPOSE="docker-compose.syntropic137.yaml"
DRAIN_TIMEOUT="${SYN_PIT_DRAIN_TIMEOUT:-10800}"
MODE="all"; DRY=0
while [ $# -gt 0 ]; do
    case "$1" in
        --ref) REF="$2"; shift 2 ;;
        --stage-only) MODE="stage"; shift ;;
        --swap-only) MODE="swap"; shift ;;
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

# A drain is a statement about ONE instant: this returns 0 only when every
# status key present is terminal. Read from status_counts, which is tallied over
# the whole collection, never from a page of rows (see the runbook, section 1).
drained() {
    api "/executions?page_size=1" "$TMP/counts.json" || return 1
    python3 - "$TMP/counts.json" <<'PY'
import json, sys
counts = json.load(open(sys.argv[1]))["status_counts"]
busy = sorted(set(counts) - {"completed", "failed", "cancelled", "interrupted"})
print(f"   status_counts: {counts}" + (f"  IN FLIGHT: {busy}" if busy else "  (drained)"))
sys.exit(1 if busy else 0)
PY
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
    [ "$MODE" = "stage" ] && { step "staged $TAG; run with --swap-only once drained"; exit 0; }
fi

step "drain: waiting for every execution to be terminal (timeout ${DRAIN_TIMEOUT}s)"
waited=0
until drained; do
    [ "$waited" -ge "$DRAIN_TIMEOUT" ] && die "not drained after ${DRAIN_TIMEOUT}s; nothing was recreated"
    sleep 60; waited=$((waited + 60))
done

step "swap: recreate api + gateway (no pull: the images are only in the host's daemon)"
# Re-checked immediately above; the swap runs in the same breath.
run remote "cd $COMPOSE_DIR && docker compose -f $COMPOSE up -d api gateway" | tail -4

step "verify: images, docker CLI, projections"
if [ "$DRY" = 0 ]; then
    running="$(remote "docker inspect syn137-api syn137-gateway --format '{{.Config.Image}}'")"
    while IFS= read -r line; do printf '   %s\n' "$line"; done <<< "$running"
    [ "$(echo "$running" | grep -c ":$TAG\$")" = 2 ] || die "a container is not on $TAG"
    remote "docker exec syn137-api sh -c 'command -v docker'" >/dev/null || die "no docker CLI in syn-api (#1216): every execution will fail at bootstrap"
    for _ in $(seq 1 30); do
        api "/health" "$TMP/health.json" 2>/dev/null && python3 -c "
import json,sys; s=json.load(open('$TMP/health.json')).get('subscription',{})
print('   subscription:', {k:s.get(k) for k in ('status','is_catching_up','lag')})
sys.exit(0 if s.get('status')=='healthy' and not s.get('is_catching_up') else 1)" && break
        sleep 10
    done || die "projections not healthy after the swap"
fi
step "PIT STOP DONE: $TAG live in $(( $(date +%s) - T0 ))s. Last check is yours: dispatch one real workflow and watch a PHASE reach running."
