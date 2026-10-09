/**
 * The page a feedback item is attached to: everything FeedbackCreate can carry
 * about where it was left, gathered at submit time. Route subject mirrors the
 * React dashboard's useFeedbackSubject (execution, session, workflow,
 * artifact, trigger detail pages).
 */
import type { FeedbackSubjectKind } from '@syn137/syn-ui-data'

const SUBJECT_ROUTES: readonly (readonly [RegExp, FeedbackSubjectKind])[] = [
  [/^\/executions\/([^/]+)/, 'execution'],
  [/^\/sessions\/([^/]+)/, 'session'],
  [/^\/workflows\/([^/]+)/, 'workflow'],
  [/^\/artifacts\/([^/]+)/, 'artifact'],
  [/^\/triggers\/([^/]+)/, 'trigger'],
]

export interface FeedbackSubject {
  kind: FeedbackSubjectKind
  id: string
}

export function subjectOf(path: string): FeedbackSubject | null {
  for (const [re, kind] of SUBJECT_ROUTES) {
    const m = re.exec(path)
    if (m?.[1]) return { kind, id: decodeURIComponent(m[1]) }
  }
  return null
}

export interface PageContext {
  url: string
  route: string
  viewportWidth: number
  viewportHeight: number
  userAgent: string
  theme: string
  hostname: string
  subject: FeedbackSubject | null
}

export function pageContext(route: string): PageContext {
  return {
    url: location.href,
    route,
    viewportWidth: innerWidth,
    viewportHeight: innerHeight,
    userAgent: navigator.userAgent,
    theme: document.documentElement.dataset.theme ?? 'syn137',
    hostname: location.hostname,
    subject: subjectOf(route),
  }
}
