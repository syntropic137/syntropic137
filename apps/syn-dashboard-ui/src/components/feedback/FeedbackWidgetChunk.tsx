/**
 * The feedback widget itself — the only module that imports the package.
 *
 * Kept in its own file with a default export so `FeedbackMount` can reach it
 * through `React.lazy(() => import(...))`. That dynamic import is what puts
 * the widget, its styles and html2canvas in a separate chunk, so a deployment
 * with the feature off never downloads any of it (#105, ADR-016).
 *
 * Nothing here decides whether the feature is on; by the time this module is
 * fetched, that has already been answered.
 */

import { FeedbackProvider, FeedbackWidget, type Theme } from '@syn137/ui-feedback-react'

import { API_BASE } from '../../api'
import { useFeedbackSubject } from '../../hooks/useFeedbackSubject'

/**
 * The widget reads its colours from CSS custom properties it sets itself, so
 * matching the dashboard is a matter of handing it our palette rather than
 * overriding its stylesheet. Literal values, not `var(--color-...)`: the
 * provider writes these into inline styles on its own subtree, and a var()
 * reference would resolve there too but leaves the widget silently unthemed
 * in any test or story rendered without index.css.
 */
const DASHBOARD_THEME: Theme = {
  primary: '#4D80FF',
  primaryHover: '#5a8cff',
  background: '#0F0F1A',
  surface: '#161625',
  surfaceHover: '#1E1E30',
  border: 'rgba(77, 128, 255, 0.15)',
  text: '#E6F2FF',
  textSecondary: '#8899BB',
  success: '#22c55e',
  error: '#ef4444',
  warning: '#f59e0b',
}

export default function FeedbackWidgetChunk() {
  const subject = useFeedbackSubject()

  return (
    <FeedbackProvider
      apiUrl={API_BASE}
      appName="syn-dashboard-ui"
      appVersion={__APP_VERSION__}
      theme={DASHBOARD_THEME}
      subject={subject}
    >
      <FeedbackWidget />
    </FeedbackProvider>
  )
}
