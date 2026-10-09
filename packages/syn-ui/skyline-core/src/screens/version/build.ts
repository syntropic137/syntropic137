/**
 * Build view-model: which release the API is running, and which bundle the
 * browser loaded. The shell's version mark, its tooltip, the `?` overlay
 * footer, the palette's Version row and every "copy for an agent" block read
 * this one function, so they cannot disagree.
 *
 * The API's `version` is PEP 440 (`0.33.2b23`); a bundle carries package.json
 * semver (`0.33.2-beta.23`). Both are compared in PEP 440 form, the mapping
 * `to_pep440` in scripts/workflows/bump_version.py applies.
 */

/** The served build block (structurally the API's BuildInfo; declared here, ADR-074). */
export interface ServedBuild {
  version: string | null
  image_tag?: string | null
  commit?: string | null
  started_at_display: string
}

export interface BuildDetail {
  term: string
  value: string
}

export interface BuildView {
  /** The short mark, e.g. `v0.33.2b23`; null until the API answers. */
  label: string | null
  /** The bundle's own release, null for an unversioned (dev) bundle. */
  ui: string | null
  /** The commit, shortened; null when the image did not stamp one. */
  commit: string | null
  /** Both releases are known and differ: a rollout in flight, or a stale tab. */
  mismatch: boolean
  /** Term and value rows for the tooltip and the overlay footer. */
  details: BuildDetail[]
  /** One plain line for clipboards and agent prompts. */
  text: string
}

/** package.json's placeholder: the bundle carries no release of its own. */
export const UNVERSIONED_UI = '0.0.0'

const SEMVER_PRERELEASE = /-(alpha|beta|rc)\.(\d+)$/
const PEP440_TAG: Record<string, string> = { alpha: 'a', beta: 'b', rc: 'rc' }
const SHORT_SHA = 7

export function toPep440(release: string): string {
  return release
    .trim()
    .replace(/^v/, '')
    .replace(SEMVER_PRERELEASE, (_, tag: string, n: string) => `${PEP440_TAG[tag] ?? tag}${Number(n)}`)
}

export function isSameRelease(a: string, b: string): boolean {
  return toPep440(a) === toPep440(b)
}

const bundleRelease = (ui: string): string | null => {
  const v = ui.trim()
  return v === '' || v === UNVERSIONED_UI ? null : v
}

/** The detail rows for a served build, in display order. */
function apiDetails(api: ServedBuild): BuildDetail[] {
  const rows: BuildDetail[] = [{ term: 'API', value: api.version ? `v${api.version}` : 'unavailable' }]
  if (api.image_tag) rows.push({ term: 'Image', value: api.image_tag })
  if (api.commit) rows.push({ term: 'Commit', value: api.commit.slice(0, SHORT_SHA) })
  rows.push({ term: 'Deployed', value: api.started_at_display })
  return rows
}

function buildText(api: ServedBuild | null | undefined, details: BuildDetail[], uiLabel: string): string {
  return api ? `Build: ${details.map((d) => `${d.term} ${d.value}`).join(' · ')}` : `Build: API unknown · UI ${uiLabel}`
}

export function buildView(api: ServedBuild | null | undefined, uiVersion: string): BuildView {
  const ui = bundleRelease(uiVersion)
  const uiLabel = ui ? `v${toPep440(ui)}` : 'unversioned'
  const label = api?.version ? `v${api.version}` : null
  const details: BuildDetail[] = [...(api ? apiDetails(api) : []), { term: 'UI', value: uiLabel }]
  const mismatch = Boolean(api?.version && ui && !isSameRelease(api.version, ui))
  const commit = api?.commit ? api.commit.slice(0, SHORT_SHA) : null
  return { label, ui, commit, mismatch, details, text: buildText(api, details, uiLabel) }
}
