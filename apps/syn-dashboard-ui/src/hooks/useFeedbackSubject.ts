/**
 * What the current page is about, for feedback context (#105, ADR-016).
 *
 * Derived from the route rather than passed down from each page: the router
 * already knows, and threading a prop through fourteen pages would leave the
 * next page to forget it. A page that is about nothing in particular — the
 * dashboard, the lists — yields null, which is a legitimate answer.
 */

import { useLocation } from 'react-router-dom'

import type { FeedbackSubject, SubjectKind } from '@syn137/ui-feedback-react'

/**
 * First path segment -> subject kind, for the detail routes only.
 * `/executions` is a list and has no subject; `/executions/:id` does.
 */
const SUBJECT_KIND_BY_SEGMENT: Record<string, SubjectKind> = {
  executions: 'execution',
  sessions: 'session',
  workflows: 'workflow',
  artifacts: 'artifact',
  triggers: 'trigger',
}

export function subjectFromPath(pathname: string): FeedbackSubject | null {
  const [segment, id] = pathname.split('/').filter(Boolean)
  if (!segment || !id) return null

  const kind = SUBJECT_KIND_BY_SEGMENT[segment]
  if (!kind) return null

  return { kind, id }
}

export function useFeedbackSubject(): FeedbackSubject | null {
  return subjectFromPath(useLocation().pathname)
}
