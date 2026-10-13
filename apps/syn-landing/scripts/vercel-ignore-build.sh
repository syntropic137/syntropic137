#!/usr/bin/env bash
# Vercel "Ignored Build Step" for syntropic137.com (vercel.json `ignoreCommand`).
# Vercel runs it from the project's root directory (apps/syn-landing).
# Exit 0 skips the build; exit 1 builds.
#
# vercel.json already limits deployments to the `release` branch
# (git.deploymentEnabled). This also skips a release deploy when nothing the
# page is built from changed since the last deployment: this app, Skyline
# (packages/syn-ui, which P5+ build the page from) or the install inputs.
# Anything it cannot decide (first deploy, a base commit missing from Vercel's
# shallow clone) builds.
set -u

if [ "${VERCEL_GIT_COMMIT_REF:-}" != "release" ]; then
  echo "Skip: ${VERCEL_GIT_COMMIT_REF:-unknown ref} is not the release branch."
  exit 0
fi

BASE="${VERCEL_GIT_PREVIOUS_SHA:-}"
if [ -z "$BASE" ] || ! git cat-file -e "${BASE}^{commit}" 2>/dev/null; then
  echo "Build: no previous deployment commit to compare against."
  exit 1
fi

if git diff --quiet "$BASE" HEAD -- . ../../packages/syn-ui ../../pnpm-lock.yaml ../../pnpm-workspace.yaml; then
  echo "Skip: nothing under apps/syn-landing, packages/syn-ui or the pnpm inputs changed since ${BASE}."
  exit 0
fi
echo "Build: the landing page or its inputs changed since ${BASE}."
exit 1
