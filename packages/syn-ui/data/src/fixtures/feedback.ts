/**
 * Feedback fixture: POST /feedback answers like the API (201 body), so the
 * modal's success path runs offline. Items are kept in memory for tests.
 */
import { ApiError } from '../client/errors'
import type { FeedbackCreate, FeedbackItem } from '../resources/feedback'
import { route } from './define'
import { FIXTURE_NOW, fakeId } from './seed'

export const fixtureFeedback: FeedbackItem[] = []

function isCreate(body: unknown): body is FeedbackCreate {
  if (typeof body !== 'object' || body === null) return false
  const b = body as Partial<Record<keyof FeedbackCreate, unknown>>
  return typeof b.url === 'string' && typeof b.app_name === 'string'
}

export const feedbackRoutes = [
  route('POST', '/feedback', ({ body }): FeedbackItem => {
    if (!isCreate(body)) {
      throw new ApiError(422, [{ loc: ['body'], msg: 'url and app_name are required', type: 'missing' }])
    }
    const at = new Date(FIXTURE_NOW).toISOString()
    const item: FeedbackItem = {
      ...body,
      id: `${fakeId(`feedback-${fixtureFeedback.length}`, 8)}-0000-4000-8000-${fakeId('fb', 12)}`,
      feedback_type: body.feedback_type ?? 'bug',
      priority: body.priority ?? 'medium',
      status: 'open',
      created_at: at,
      updated_at: at,
      media_count: 0,
    }
    fixtureFeedback.push(item)
    return item
  }),
]
