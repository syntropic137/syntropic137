#!/usr/bin/env bash
# Build AEF Workspace Docker Image
#
# Usage:
#   ./docker/workspace/build.sh              # Build latest
#   ./docker/workspace/build.sh v1.0.0       # Build with version tag
#   ./docker/workspace/build.sh --push       # Build and push to registry
#
# See ADR-021: Isolated Workspace Architecture

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

IMAGE_NAME="${AEF_WORKSPACE_IMAGE:-aef-workspace-claude}"
REGISTRY="${AEF_REGISTRY:-}"
VERSION="${1:-latest}"
PUSH=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --push)
            PUSH=true
            shift
            ;;
        *)
            VERSION="$1"
            shift
            ;;
    esac
done

# Construct full image name
if [[ -n "$REGISTRY" ]]; then
    FULL_IMAGE="${REGISTRY}/${IMAGE_NAME}:${VERSION}"
else
    FULL_IMAGE="${IMAGE_NAME}:${VERSION}"
fi

echo "🔨 Building AEF Workspace Image"
echo "   Image: ${FULL_IMAGE}"
echo "   Context: ${REPO_ROOT}"
echo ""

# Build the image
docker build \
    --file "${SCRIPT_DIR}/Dockerfile" \
    --tag "${FULL_IMAGE}" \
    --label "org.opencontainers.image.source=https://github.com/AgentParadise/agentic-engineering-framework" \
    --label "org.opencontainers.image.description=AEF Isolated Workspace for Claude Agents" \
    --label "org.opencontainers.image.version=${VERSION}" \
    "${REPO_ROOT}"

# Also tag as latest if building a version
if [[ "$VERSION" != "latest" ]]; then
    if [[ -n "$REGISTRY" ]]; then
        docker tag "${FULL_IMAGE}" "${REGISTRY}/${IMAGE_NAME}:latest"
    else
        docker tag "${FULL_IMAGE}" "${IMAGE_NAME}:latest"
    fi
fi

echo ""
echo "✅ Build complete: ${FULL_IMAGE}"

# Push if requested
if [[ "$PUSH" == "true" ]]; then
    echo ""
    echo "📤 Pushing to registry..."
    docker push "${FULL_IMAGE}"
    if [[ "$VERSION" != "latest" ]]; then
        if [[ -n "$REGISTRY" ]]; then
            docker push "${REGISTRY}/${IMAGE_NAME}:latest"
        else
            docker push "${IMAGE_NAME}:latest"
        fi
    fi
    echo "✅ Push complete"
fi

echo ""
echo "🚀 To test the image:"
echo "   docker run --rm -it ${FULL_IMAGE} bash"
