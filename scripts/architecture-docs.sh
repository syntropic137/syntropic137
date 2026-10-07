#!/usr/bin/env bash
# Regenerate every architecture artifact derived from the VSA manifest, or
# fail when the committed copies are stale.
#
#   scripts/architecture-docs.sh          # write into the repo
#   scripts/architecture-docs.sh --check  # regenerate into a temp dir and diff
#
# Pipeline: source tree -> `vsa manifest` -> canonical manifest
#   -> vsa-visualizer (vsa-overview.svg) + generate-architecture-docs.py (md).
# The manifest itself is gitignored (#297), so it is always rebuilt from
# source first; a check that read a stale local manifest would prove nothing.
#
# Needs `vsa` (setup-vsa in CI), node and pnpm. Not part of preflight-agent:
# the agent image has no vsa.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

GENERATED=(
    docs/architecture/vsa-overview.svg
    docs/architecture/projection-subscriptions.md
    docs/architecture/event-flows/README.md
    README.md
)

mode=write
if [[ "${1:-}" == "--check" ]]; then
    mode=check
fi

if ! command -v vsa >/dev/null 2>&1; then
    echo "❌ vsa CLI not found. Install it from the submodule:" >&2
    echo "   (cd lib/event-sourcing-platform/vsa && cargo install --path vsa-cli --locked)" >&2
    exit 127
fi

ESP=lib/event-sourcing-platform
VISUALIZER="$ESP/vsa/vsa-visualizer"
MANIFEST=.topology/syn-manifest.json

# The visualizer belongs to ESP's pnpm workspace; install only its closure.
# Output is kept so a failed build names itself instead of the next step.
(cd "$ESP" && pnpm install --frozen-lockfile --ignore-scripts --filter @vsa/visualizer... >/dev/null)
(cd "$ESP" && pnpm --filter @vsa/visualizer run build >/dev/null)

mkdir -p "$(dirname "$MANIFEST")"
vsa manifest --config vsa.yaml --output "$MANIFEST" --include-domain >/dev/null

if [[ "$mode" == write ]]; then
    out_root=.
else
    out_root=$(mktemp -d)
    trap 'rm -rf "$out_root"' EXIT
    # README.md is edited in place (only its counts row), so seed the copy.
    cp README.md "$out_root/README.md"
fi

# Canonicalises $MANIFEST in place, so it must run before the visualizer.
uv run python scripts/generate-architecture-docs.py \
    --manifest "$MANIFEST" --out-root "$out_root" >/dev/null
node "$VISUALIZER/dist/index.js" "$MANIFEST" \
    --format svg --type architecture --output "$out_root/docs/architecture" >/dev/null

if [[ "$mode" == write ]]; then
    echo "✅ Regenerated: ${GENERATED[*]}"
    exit 0
fi

stale=()
for file in "${GENERATED[@]}"; do
    if ! cmp -s "$file" "$out_root/$file"; then
        stale+=("$file")
        diff -u "$file" "$out_root/$file" | head -40 >&2 || true
    fi
done

if ((${#stale[@]})); then
    echo "❌ Architecture docs are stale: ${stale[*]}" >&2
    echo "   Run 'just docs-regen' and commit the result." >&2
    exit 1
fi
echo "✅ Architecture docs match the source tree"
