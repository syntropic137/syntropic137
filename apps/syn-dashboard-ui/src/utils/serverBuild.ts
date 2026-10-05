/**
 * How the dashboard reads and presents the API's build.
 */

import type { BuildInfo } from '../api'
import { formatRelativeTime, formatTimestampLocale } from './dateFormatters'

/*
 * Do two spellings name the same release?
 *
 * The bundle and the API carry the same release, written two ways.
 * `__APP_VERSION__` is package.json's `0.33.0-beta.1`. The API reads its
 * installed metadata, which Python normalizes to PEP 440: `0.33.0b1`. Compared
 * as strings, every beta would look like a new deploy. So both are put in the
 * PEP 440 form first, the same mapping `to_pep440` in
 * `scripts/workflows/bump_version.py` applies when it writes the release.
 */

const SEMVER_PRERELEASE = /-(alpha|beta|rc)\.(\d+)$/
const PEP440_TAG: Record<string, string> = { alpha: 'a', beta: 'b', rc: 'rc' }

function toPep440(release: string): string {
  return release
    .trim()
    .replace(/^v/, '')
    .replace(SEMVER_PRERELEASE, (_, tag: string, n: string) => `${PEP440_TAG[tag]}${Number(n)}`)
}

export function isSameRelease(a: string, b: string): boolean {
  return toPep440(a) === toPep440(b)
}

const SHORT_SHA_LENGTH = 7

/** The label for the running build: the image tag if stamped, else the release, else the bundle's own until the server answers. */
export function versionLabel(build: BuildInfo | null, bundleVersion: string = __APP_VERSION__): string {
  if (build?.image_tag) return build.image_tag
  return `v${build?.version ?? bundleVersion}`
}

/**
 * "Deployed <local date/time> (<2h ago>) · commit <short sha>". The commit
 * part is left out when the image did not stamp one. The time is rendered here
 * rather than from `started_at_display` because only the browser knows the
 * viewer's time zone, and "ago" has to be measured at render time.
 */
export function deployedTooltipText(build: BuildInfo, now: number = Date.now()): string {
  const deployed = `Deployed ${formatTimestampLocale(build.started_at)} (${formatRelativeTime(build.started_at, now)})`
  return build.commit ? `${deployed} · commit ${build.commit.slice(0, SHORT_SHA_LENGTH)}` : deployed
}
