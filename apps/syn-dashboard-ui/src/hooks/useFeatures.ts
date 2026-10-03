/**
 * Runtime feature flags, fetched once per page load.
 *
 * The dashboard is one image for every deployment, so it cannot learn from a
 * build-time Vite variable which optional features an operator has enabled —
 * that would make enabling one a rebuild. It asks the API instead (#105,
 * ADR-016).
 *
 * Failure is not an error state worth surfacing: a deployment that cannot
 * answer has no optional features on, which is exactly the default. So this
 * returns flags and nothing else, and every consumer treats "not yet known"
 * and "off" identically.
 */

import { useEffect, useState } from 'react'

import { getFeatures, type Features } from '../api'

const NO_FEATURES: Features = { ui_feedback: false }

export function useFeatures(): Features {
  const [features, setFeatures] = useState<Features>(NO_FEATURES)

  useEffect(() => {
    let cancelled = false
    getFeatures()
      .then((result) => {
        if (!cancelled) setFeatures(result)
      })
      .catch(() => {
        // Stay at the defaults. See the module comment.
      })
    return () => {
      cancelled = true
    }
  }, [])

  return features
}
