/**
 * The build the API is running right now, kept current while the page is open.
 *
 * `__APP_VERSION__` is baked into the bundle, so it names the build this page
 * was LOADED from and cannot change until a reload. That is the build a user
 * is running, but it is not the one that is deployed, and after a redeploy the
 * two differ silently. This hook asks the server instead. It fetches on mount,
 * every minute, and again when the tab becomes visible, so a laptop opened the
 * morning after a deploy shows the new build at once. No SSE stream carries
 * build identity, so this polls. The poll is `useSerialRefresh`'s, which pauses
 * while the tab is hidden and never stacks requests.
 *
 * A failed fetch keeps the last answer: an API that blips has not changed
 * build.
 */

import { useCallback, useEffect, useState } from 'react'

import { getBuildInfo, type BuildInfo } from '../api'
import { isSameRelease } from '../utils/serverBuild'
import { ifStillWanted } from './serialRefreshLoop'
import { useSerialRefresh } from './useSerialRefresh'

/** How often to ask which build is deployed. A deploy is rare; a minute is prompt enough. */
export const BUILD_POLL_INTERVAL_MS = 60_000

export interface ServerBuild {
  /** The API's build, or null until the first answer arrives. */
  build: BuildInfo | null
  /**
   * The API is running a different release than the one this bundle was built
   * from, so the page is stale and a reload would pick up the deployed one.
   * False while the API cannot name its release, because "unknown" is not
   * evidence of a new deploy.
   */
  bundleIsStale: boolean
}

export function useServerBuild(bundleVersion: string = __APP_VERSION__): ServerBuild {
  const [build, setBuild] = useState<BuildInfo | null>(null)

  const fetchBuild = useCallback(
    (signal: AbortSignal): Promise<void> =>
      getBuildInfo(signal).then(ifStillWanted(signal, setBuild)),
    [],
  )

  const { refetch } = useSerialRefresh({ fetch: fetchBuild, pollIntervalMs: BUILD_POLL_INTERVAL_MS })

  useEffect(() => {
    refetch()
  }, [refetch])

  const serverVersion = build?.version ?? null
  return {
    build,
    bundleIsStale: serverVersion !== null && !isSameRelease(bundleVersion, serverVersion),
  }
}
