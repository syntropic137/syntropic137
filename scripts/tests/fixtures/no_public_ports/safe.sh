#!/usr/bin/env bash
# `-p` spellings that must never be flagged, including the three non-publish
# uses of the same flag that share this repo's justfile.
docker run -p 127.0.0.1:5432:5432 postgres
docker run --publish "127.0.0.1:${PROXY_PORT}:8080" img
docker run -p '[::1]:5432:5432' postgres
mkdir -p workspaces
cargo build --release --manifest-path lib/x/Cargo.toml -p aps-cli
echo "         -p syntropic137_${_owner} \\"
