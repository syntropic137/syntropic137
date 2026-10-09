# Build image for Anthropic's OSS Scanner (https://github.com/anthropics/oss-scanner).
#
# Contract (templates/Dockerfile in that repo):
#   - build context is a plain `git clone` of this repo (no --recurse-submodules),
#     so `COPY . /src` brings .git along and submodules are fetched here;
#   - network is available ONLY during this build; the scan runs offline, so
#     every dependency an agent needs to build and test must be installed now;
#   - the final stage needs apt (the scanner adds its own tools layer on top).
#
# Local check (from the repo root, in a full clone - a worktree's .git is a file
# and the submodule step cannot run there):
#   docker build -f .oss-scanner/Dockerfile -t syn137-oss-scanner .
#   docker run --rm --network none syn137-oss-scanner \
#     sh -c 'cd /src && uv run pytest -q -m unit -x packages/syn-shared'
#
# No secrets, no Docker-in-Docker: tests that need Postgres, Redis, the event
# store or Docker are marked `integration` and excluded by pytest's addopts.

FROM node:22-bookworm

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates git build-essential pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Same uv the production API image uses (infra/docker/images/syn-api/Dockerfile).
COPY --from=ghcr.io/astral-sh/uv:0.10.6 /uv /uvx /usr/local/bin/

# Keep uv's interpreter and cache inside the image so nothing is fetched at scan time.
ENV UV_PYTHON_INSTALL_DIR=/opt/uv/python \
    UV_CACHE_DIR=/opt/uv/cache \
    UV_LINK_MODE=copy \
    UV_FROZEN=1 \
    PNPM_HOME=/opt/pnpm \
    PATH=/opt/pnpm:$PATH

# pnpm major matches CI (pnpm/action-setup version: 10) and packageManager in apps/syn-cli-node.
RUN npm install -g pnpm@10.24.0 && pnpm --version

# scanner contract: the checkout lives inside the image, at /src
COPY . /src
WORKDIR /src

# The uv workspace depends on code in lib/ submodules (event-sourcing-python,
# agentic-isolation/-events/-logging, apss-session-capture). The scanner clones
# without submodules, so fetch them at the exact gitlink SHAs recorded in this
# commit. All submodule repos are public.
RUN git config --global --add safe.directory '*' \
    && git submodule sync \
    && git submodule update --init --depth 1 \
         lib/event-sourcing-platform \
         lib/agentic-workspace \
         lib/agent-paradise-standards-system \
    && git submodule status

# Python: interpreter from .python-version, full workspace incl. the dev group (pytest, pyright, ruff).
RUN uv python install \
    && uv sync --all-packages --group dev \
    && uv run python -c "import syn_api, syn_domain, syn_adapters, syn_shared, event_sourcing; print('python workspace ok')"

# Node: whole pnpm workspace (CLI, dashboard, docs, openclaw plugin, ui-feedback widget).
# --ignore-scripts mirrors CI's supply-chain posture.
RUN pnpm install --frozen-lockfile --ignore-scripts

# Build the CLI so dist/ exists for anyone exercising `syn` offline.
RUN pnpm --dir apps/syn-cli-node run build || echo "WARNING: syn-cli-node build failed"

# After this point the scan is offline: make uv never try the network.
ENV UV_OFFLINE=1

# Cheap tests, bounded, never fatal (the template's rule: a failing test must not abort the build).
RUN timeout 1200 uv run pytest -m unit -q -x -n auto -p no:cacheprovider \
      || echo "WARNING: python unit tests reported failures"
RUN timeout 600 pnpm --dir apps/syn-cli-node run test \
      || echo "WARNING: syn-cli-node tests reported failures"
RUN timeout 600 pnpm --dir apps/syn-dashboard-ui run test \
      || echo "WARNING: syn-dashboard-ui tests reported failures"
