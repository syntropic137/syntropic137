/**
 * In-app feedback (lib/ui-feedback, ADR-016, #1385). Create only: the Skyline
 * modal files an item and never lists them, so the list, stats and media
 * routes the React widget uses are not ported.
 *
 * The routes exist only on an API built with the feedback extra, and answer
 * 404 while SYN_UI_FEEDBACK_ENABLED is off. Gate the UI on `getFeatures()`.
 */
import { request } from '../client'
import type { components } from '../generated/api-types'

export type FeedbackCreate = components['schemas']['FeedbackCreate']
export type FeedbackItem = components['schemas']['FeedbackItem']
export type FeedbackType = components['schemas']['FeedbackType']
export type FeedbackPriority = components['schemas']['Priority']

/** Every `FeedbackType`, in the React widget's order. A new upstream member is a compile error here. */
export const FEEDBACK_TYPES = ['bug', 'feature', 'ui_ux', 'performance', 'question', 'other'] as const satisfies readonly FeedbackType[]

type MissingFeedbackType = Exclude<FeedbackType, (typeof FEEDBACK_TYPES)[number]>
const _allFeedbackTypes: MissingFeedbackType extends never ? true : false = true
void _allFeedbackTypes

/** Every `Priority`, low to critical. The API defaults to medium. */
export const FEEDBACK_PRIORITIES = ['low', 'medium', 'high', 'critical'] as const satisfies readonly FeedbackPriority[]

/** File one feedback item. A mutation: nothing in the cache reads feedback, so nothing is invalidated. */
export function createFeedback(body: FeedbackCreate, signal?: AbortSignal): Promise<FeedbackItem> {
  return request('/feedback', { method: 'POST', body, signal })
}
