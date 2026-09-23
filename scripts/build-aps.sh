#!/usr/bin/env bash
# Called from the repo root by just. Only CI's exact-key cache may skip Cargo.
set -euo pipefail

apss_path=lib/agent-paradise-standards-system
apss_bin="$apss_path/target/release/apss-dev"

if [[ "${GITHUB_ACTIONS:-}" == true && "${SYN_APS_CACHE_HIT:-}" == true ]]; then
    expected=$(git rev-parse "HEAD:$apss_path")
    actual=$(git -C "$apss_path" rev-parse HEAD)
    dirty=$(git -C "$apss_path" status --porcelain --untracked-files=all)
    if [[ "$actual" == "$expected" && -z "$dirty" && -x "$apss_bin" ]]; then
        # Detect a corrupt or incompatible executable before accepting the hit.
        "$apss_bin" --version
        echo "Reusing APS CLI from exact CI cache ($expected)"
        exit 0
    fi
    echo "APS cache cannot be reused for this checkout; rebuilding"
fi

# No presence/mtime shortcut locally: source edits must always reach Cargo.
echo "Building APS CLI"
cargo build --locked --release --manifest-path "$apss_path/Cargo.toml" -p aps-cli
