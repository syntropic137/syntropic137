# Release recipes: build, push, verify and re-tag container images, and
# upload the selfhost release assets.
#
# Imported by the root justfile (`import 'just/release.just'`), so every
# recipe keeps its name and runs from the repository root exactly as before.
# Split out so CODEOWNERS can own what publishes images (supply chain) without
# owning the whole justfile: see .github/CODEOWNERS.

registry := "ghcr.io/syntropic137"

# Build and push core container images locally (skips event-store and agentic-workspace — use release-retag for those)
release-local version:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "🚀 Local release: {{version}}"
    echo ""

    # syn-api reports this as its commit on /version (#1473). A dirty tree is
    # not the commit HEAD names, and stamping nothing would ship `commit: null`,
    # so refuse before anything is logged in to or pushed.
    if [ -n "$(git status --porcelain)" ]; then
        echo "❌ Working tree is dirty: commit or stash first, so syn-api's /version names the tree that shipped" >&2
        exit 1
    fi
    build_commit="$(git rev-parse HEAD)"

    # Login to GHCR
    gh auth token | docker login ghcr.io -u syntropic137 --password-stdin
    echo ""

    # Ensure buildx builder exists
    docker buildx inspect multiarch >/dev/null 2>&1 || docker buildx create --name multiarch
    docker buildx use multiarch

    # Images to build (order: fast first)
    FAILED=()
    for image in token-injector sidecar-proxy syn-collector syn-dashboard-ui syn-api syn-gateway; do
        # build_args holds extra `--build-arg` flags and is expanded UNQUOTED on
        # purpose: the values are literal tokens with no whitespace, and this
        # stays correct on the bash 3.2 that ships with macOS, where an empty
        # array under `set -u` does not.
        build_args=""
        case "$image" in
            token-injector)   dockerfile="docker/token-injector/Dockerfile"; context="docker/token-injector" ;;
            sidecar-proxy)    dockerfile="docker/sidecar-proxy/Dockerfile"; context="docker/sidecar-proxy" ;;
            syn-collector)    dockerfile="packages/syn-collector/Dockerfile"; context="." ;;
            syn-dashboard-ui) dockerfile="apps/syn-dashboard-ui/Dockerfile"; context="." ;;
            syn-api)          dockerfile="infra/docker/images/syn-api/Dockerfile"; context="."
                              # Also the Dockerfile default since #1216. Stated
                              # here too so this recipe declares what it needs
                              # rather than inheriting it silently - inheriting
                              # it silently is the exact shape of the bug this
                              # line closes.
                              # SYN_BUILD_* are the image's identity on
                              # /version, measured by the same fitness test.
                              build_args="--build-arg INCLUDE_DOCKER_CLI=1 --build-arg SYN_BUILD_IMAGE_TAG={{version}} --build-arg SYN_BUILD_COMMIT=$build_commit" ;;
            syn-gateway)      dockerfile="infra/docker/images/gateway/Dockerfile"; context="." ;;
        esac
        echo "📦 Building $image..."
        if docker buildx build $build_args --platform linux/amd64,linux/arm64 \
            -f "$dockerfile" \
            -t "{{registry}}/$image:{{version}}" \
            --push "$context" \
           && just verify-image-capabilities "$image" "{{registry}}/$image:{{version}}"; then
            echo "✅ $image pushed and verified"
        else
            echo "❌ $image failed"
            FAILED+=("$image")
        fi
        echo ""
    done

    # Summary
    echo "=== Release Summary ==="
    echo "Version: {{version}}"
    echo "Registry: {{registry}}"
    if [ ${#FAILED[@]} -eq 0 ]; then
        echo "✅ All images pushed successfully"
    else
        echo "❌ Failed: ${FAILED[*]}"
        exit 1
    fi

# Assert a built image actually HAS the binaries it cannot run without.
#
# Test the capability, not the flag. `just release-local` could pass every
# build arg correctly and still ship an unusable image - a Dockerfile stage
# that stops copying a binary forward, an upstream tarball that moves, a base
# image that drops a package. Asserting "does the pushed artifact have docker"
# survives all of those; asserting "did we pass --build-arg" only restates the
# recipe above and goes stale with it.
#
# This exists because #1216 was invisible until an execution was attempted:
# the API answered /health, served every list endpoint, and failed every
# workflow at bootstrap having spent $0.00. smoke-test.yml already carried a
# comment about "issues like INCLUDE_DOCKER_CLI not being passed" - the
# knowledge lived next to a detector instead of next to the recipe that
# causes the problem, so the local release path walked into it anyway.
#
#   image  short name from the release matrix (chooses the capability list)
#   ref    full pullable reference to inspect
#
# Callable on its own, including from CI:
#   just verify-image-capabilities syn-api ghcr.io/syntropic137/syn-api:v0.28.0

verify-image-capabilities image ref:
    #!/usr/bin/env bash
    set -euo pipefail
    case "{{image}}" in
        # syn-api resolves every workspace image through `docker` and verifies
        # its signature with `cosign` (syn_adapters/workspace_backends/
        # image_verification.py). Both look the binary up with shutil.which and
        # both fail closed, so either one missing means zero executions start.
        syn-api)
            required="docker cosign" ;;
        syn-gateway|syn-collector|syn-dashboard-ui|sidecar-proxy|token-injector)
            required="" ;;
        # An unlisted image is not "needs nothing", it is "nobody decided yet".
        # Failing here costs one line in this case statement; guessing costs
        # another silent release.
        *)
            echo "❌ verify-image-capabilities: no capability list for '{{image}}'" >&2
            echo "   Add one to this recipe before releasing that image." >&2
            exit 1 ;;
    esac

    if [ -z "$required" ]; then
        echo "🔍 {{image}}: no required binaries"
        exit 0
    fi

    # Without this the loop below reports every binary as missing, and the
    # message blames the image for the state of the host running the check.
    if ! command -v docker >/dev/null 2>&1; then
        echo "❌ verify-image-capabilities needs docker to inspect {{ref}}," >&2
        echo "   and docker is not on PATH here. Cannot verify {{image}}." >&2
        exit 1
    fi

    echo "🔍 Verifying {{ref}} provides: $required"
    missing=""
    for bin in $required; do
        if ! docker run --rm --entrypoint sh "{{ref}}" -c "command -v $bin" >/dev/null 2>&1; then
            missing="$missing $bin"
        fi
    done

    if [ -n "$missing" ]; then
        echo "❌ {{ref}} is missing:$missing" >&2
        echo "   This image cannot provision a workspace. Do not deploy it." >&2
        echo "   Fix the build and re-push the same tag." >&2
        exit 1
    fi
    echo "✅ {{image}}: $required present"

# Re-tag an existing image version without rebuilding (e.g., event-store)
release-retag image from to:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "🏷️  Re-tagging {{registry}}/{{image}}:{{from}} → {{to}}"
    gh auth token | docker login ghcr.io -u syntropic137 --password-stdin
    docker buildx imagetools create \
        "{{registry}}/{{image}}:{{from}}" \
        --tag "{{registry}}/{{image}}:{{to}}"
    echo "✅ Done"

# Upload selfhost assets to a GitHub release
release-assets version:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "📎 Uploading selfhost assets to {{version}}"
    gh release upload "{{version}}" \
        docker/docker-compose.syntropic137.yaml \
        docker/selfhost.env.example \
        docker/selfhost-entrypoint.sh \
        --repo syntropic137/syntropic137 --clobber
    echo "✅ Assets uploaded"

# Full local release: build images + re-tag event-store + upload assets
# Usage: just release-local-full v0.17.1 v0.17.0
#   version: the new tag to create
#   from: existing tag to re-tag event-store/agentic-workspace from (they rarely change)
release-local-full version from:
    #!/usr/bin/env bash
    set -euo pipefail
    just release-local "{{version}}"
    just release-retag event-store "{{from}}" "{{version}}"
    just release-retag agentic-workspace "{{from}}" "{{version}}"
    just release-assets "{{version}}"
    echo ""
    echo "🎉 Full release complete: {{version}}"
    echo "   Test with: SYN_VERSION={{version}} docker compose -f docker/docker-compose.syntropic137.yaml pull"
