/** Labels, hotkeys and colour tokens for feedback types and priorities (React widget parity). */
import type { FeedbackPriority, FeedbackStatus, FeedbackType } from '@syn137/syn-ui-data'

export interface Choice<V extends string> {
  value: V
  label: string
  /** Single key that picks it while the dialog is open and focus is not in a text field. */
  key: string
  /** CSS custom property holding its colour. */
  color: string
}

export const TYPE_CHOICES: readonly Choice<FeedbackType>[] = [
  { value: 'bug', label: 'Bug', key: 'b', color: 'var(--sky-feedback-type-bug)' },
  { value: 'feature', label: 'Feature', key: 'f', color: 'var(--sky-feedback-type-feature)' },
  { value: 'ui_ux', label: 'UI/UX', key: 'u', color: 'var(--sky-feedback-type-ui-ux)' },
  { value: 'performance', label: 'Perf', key: 'p', color: 'var(--sky-feedback-type-performance)' },
  { value: 'question', label: 'Question', key: 'q', color: 'var(--sky-feedback-type-question)' },
  { value: 'other', label: 'Other', key: 'o', color: 'var(--sky-feedback-type-other)' },
]

export const PRIORITY_CHOICES: readonly Choice<FeedbackPriority>[] = [
  { value: 'low', label: 'Low', key: '1', color: 'var(--sky-feedback-priority-low)' },
  { value: 'medium', label: 'Medium', key: '2', color: 'var(--sky-feedback-priority-medium)' },
  { value: 'high', label: 'High', key: '3', color: 'var(--sky-feedback-priority-high)' },
  { value: 'critical', label: 'Critical', key: '4', color: 'var(--sky-feedback-priority-critical)' },
]

export const STATUS_LABEL = {
  open: 'Open',
  in_progress: 'In progress',
  resolved: 'Resolved',
  closed: 'Closed',
  wont_fix: "Won't fix",
} as const satisfies Record<FeedbackStatus, string>

export const typeChoice = (v: FeedbackType): Choice<FeedbackType> => TYPE_CHOICES.find((c) => c.value === v) ?? TYPE_CHOICES[0]!

/** Same defaults as the React form: bug, low. */
export const DEFAULT_TYPE: FeedbackType = 'bug'
export const DEFAULT_PRIORITY: FeedbackPriority = 'low'

export const APP_NAME = 'syn-ui'
