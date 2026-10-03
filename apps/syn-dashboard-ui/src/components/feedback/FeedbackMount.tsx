/**
 * Mounts the in-app feedback widget on every page, when it is enabled.
 *
 * Rendered once at the app root as a SIBLING of the routes rather than a
 * wrapper around them: the widget is fixed-position and needs no place in the
 * layout, and wrapping would remount the whole tree the moment the feature
 * flag resolves.
 *
 * `ui_feedback` is false until the API answers, so the default path — an
 * open-source deployment with the flag off — renders nothing and fetches no
 * chunk at all (#105, ADR-016).
 */

import { lazy, Suspense } from 'react'

import { useFeatures } from '../../hooks/useFeatures'

const FeedbackWidgetChunk = lazy(() => import('./FeedbackWidgetChunk'))

export function FeedbackMount() {
  const { ui_feedback: enabled } = useFeatures()

  if (!enabled) return null

  // No fallback: the widget is a floating button, and a spinner in its place
  // would be more distracting than its arriving a moment late.
  return (
    <Suspense fallback={null}>
      <FeedbackWidgetChunk />
    </Suspense>
  )
}
