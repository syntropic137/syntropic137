#!/usr/bin/env bash
# Regenerate every architecture artifact derived from the source tree, or fail
# when the committed copies are stale.
#
#   scripts/architecture-docs.sh          # write into the repo
#   scripts/architecture-docs.sh --check  # regenerate into a temp dir and diff
#
# Two pipelines, because the two outputs need different manifests (#1782):
#
#   markdown  source tree -> scripts/architecture_manifest.py
#               -> generate-architecture-docs.py (5 md/mdx files)
#             Needs only uv, so it runs everywhere, agent workspaces included.
#   svg       source tree -> `vsa manifest` (canonicalised)
#               -> ESP's vsa-visualizer -> vsa-overview.svg
#             Needs `vsa` (setup-vsa in CI), node and pnpm. Without vsa or pnpm
#             it prints `NOT RUN: vsa-overview.svg` and neither writes nor
#             checks the svg; CI's preflight job has both, so CI checks all 6.
#
# ci/fitness/code_quality/test_architecture_manifest_parity.py proves the two
# manifests agree on every field the markdown generator reads. Manifests are
# gitignored (#297) and always rebuilt from source first; a check that read a
# stale local manifest would prove nothing.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

SVG=docs/architecture/vsa-overview.svg
MARKDOWN=(
    docs/architecture/projection-subscriptions.md
    docs/architecture/event-flows/README.md
    README.md
    apps/syn-docs/content/docs/guide/architecture.mdx
    apps/syn-docs/content/docs/architecture/index.mdx
)

mode=write
if [[ "${1:-}" == "--check" ]]; then
    mode=check
fi

ESP=lib/event-sourcing-platform
VISUALIZER="$ESP/vsa/vsa-visualizer"
MANIFEST_DIR=.topology

if [[ "$mode" == write ]]; then
    out_root=.
else
    out_root=$(mktemp -d)
    trap 'rm -rf "$out_root"' EXIT
    # README.md and the docs pages are edited in place (only their generated
    # cells), so seed the copies.
    for page in README.md apps/syn-docs/content/docs/guide/architecture.mdx \
        apps/syn-docs/content/docs/architecture/index.mdx; do
        mkdir -p "$out_root/$(dirname "$page")"
        cp "$page" "$out_root/$page"
    done
fi
mkdir -p "$MANIFEST_DIR"

docs_manifest="$MANIFEST_DIR/syn-manifest.json"
uv run python scripts/architecture_manifest.py --output "$docs_manifest" >/dev/null
uv run python scripts/generate-architecture-docs.py \
    --manifest "$docs_manifest" --out-root "$out_root" >/dev/null
generated=("${MARKDOWN[@]}")

if command -v vsa >/dev/null 2>&1 && command -v pnpm >/dev/null 2>&1; then
    svg_manifest="$MANIFEST_DIR/syn-vsa-manifest.json"
    # The visualizer belongs to ESP's pnpm workspace; install only its closure.
    # Output is kept so a failed build names itself instead of the next step.
    (cd "$ESP" && pnpm install --frozen-lockfile --ignore-scripts --filter @vsa/visualizer... >/dev/null)
    (cd "$ESP" && pnpm --filter @vsa/visualizer run build >/dev/null)
    vsa manifest --config vsa.yaml --output "$svg_manifest" --include-domain >/dev/null
    # The renderer prints arrays in the order given; vsa's order varies by run.
    uv run python scripts/generate-architecture-docs.py \
        --manifest "$svg_manifest" --canonicalize-only >/dev/null
    node "$VISUALIZER/dist/index.js" "$svg_manifest" \
        --format svg --type architecture --output "$out_root/docs/architecture" >/dev/null
    generated+=("$SVG")
else
    echo "⚠️  NOT RUN: $SVG (needs vsa + pnpm; CI checks it)" >&2
fi

if [[ "$mode" == write ]]; then
    echo "✅ Regenerated: ${generated[*]}"
    exit 0
fi

stale=()
for file in "${generated[@]}"; do
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
echo "✅ Architecture docs match the source tree: ${generated[*]}"
