/**
 * Feedback fixtures: create, list, stats and the multipart media upload
 * answer like the API (lib/ui-feedback), so the bubble runs offline. Items
 * and media are kept in memory for tests.
 */
import { ApiError } from '../client/errors'
import {
  FEEDBACK_AUDIO_TYPES,
  FEEDBACK_IMAGE_TYPES,
  FEEDBACK_MAX_UPLOAD_BYTES,
  type FeedbackCreate,
  type FeedbackItem,
  type FeedbackItemWithMedia,
  type FeedbackMedia,
  type FeedbackMediaType,
  type FeedbackStats,
} from '../resources/feedback'
import { notFound, route } from './define'
import { FIXTURE_NOW, fakeId } from './seed'

export const fixtureFeedback: FeedbackItem[] = []
export const fixtureFeedbackMedia: FeedbackMedia[] = []
/** Uploaded bytes by media id, so GET .../media/:id can answer with them. */
const mediaBlobs = new Map<string, Blob>()
const STATUSES = ['open', 'in_progress', 'resolved', 'closed', 'wont_fix'] as const

function findItem(id: string): FeedbackItem {
  const item = fixtureFeedback.find((i) => i.id === id)
  if (!item) notFound('Feedback')
  return item
}

function applyUpdate(item: FeedbackItem, body: unknown): void {
  if (typeof body !== 'object' || body === null) throw new ApiError(422, 'JSON body required')
  const status = 'status' in body ? body.status : undefined
  if (status !== undefined && status !== null) {
    if (!(STATUSES as readonly unknown[]).includes(status)) throw new ApiError(422, 'invalid status')
    item.status = status as FeedbackItem['status']
    item.resolved_at = status === 'resolved' ? new Date(FIXTURE_NOW).toISOString() : null
  }
  item.updated_at = new Date(FIXTURE_NOW).toISOString()
}

function isCreate(body: unknown): body is FeedbackCreate {
  if (typeof body !== 'object' || body === null) return false
  const b = body as Partial<Record<keyof FeedbackCreate, unknown>>
  return typeof b.url === 'string' && typeof b.app_name === 'string'
}

const isMediaType = (v: unknown): v is FeedbackMediaType => v === 'screenshot' || v === 'voice_note'
const isImageType = (v: string): boolean => (FEEDBACK_IMAGE_TYPES as readonly string[]).includes(v)
const isAudioType = (v: string): boolean => (FEEDBACK_AUDIO_TYPES as readonly string[]).includes(v.split(';', 1)[0] ?? '')

function stats(items: readonly FeedbackItem[]): FeedbackStats {
  const by_status = { open: 0, in_progress: 0, resolved: 0, closed: 0, wont_fix: 0 }
  const by_type = { bug: 0, feature: 0, ui_ux: 0, performance: 0, question: 0, other: 0 }
  const by_priority = { low: 0, medium: 0, high: 0, critical: 0 }
  const by_app: Record<string, number> = {}
  for (const i of items) {
    by_status[i.status] += 1
    by_type[i.feedback_type] += 1
    by_priority[i.priority] += 1
    by_app[i.app_name] = (by_app[i.app_name] ?? 0) + 1
  }
  return { total: items.length, by_status, by_type, by_priority, by_app }
}

export const feedbackRoutes = [
  route('GET', '/feedback/stats', ({ query }): FeedbackStats => {
    const app = query.get('app')
    return stats(app ? fixtureFeedback.filter((i) => i.app_name === app) : fixtureFeedback)
  }),
  route('GET', '/feedback', ({ query }) => {
    const app = query.get('app')
    const status = query.get('status')
    const limit = Number(query.get('limit') ?? 50)
    const items = fixtureFeedback.filter((i) => (!app || i.app_name === app) && (!status || i.status === status)).reverse()
    return { items: items.slice(0, limit), total: items.length, page: 1, page_size: limit }
  }),
  route('GET', '/feedback/:feedbackId', ({ params }): FeedbackItemWithMedia => {
    const item = findItem(params.feedbackId ?? '')
    const media = fixtureFeedbackMedia
      .filter((m) => m.feedback_id === item.id)
      .map((m) => ({ id: m.id, media_type: m.media_type, mime_type: m.mime_type, file_name: m.file_name, file_size: m.file_size, created_at: m.created_at }))
    return { ...item, media }
  }),
  route('PATCH', '/feedback/:feedbackId', ({ params, body }): FeedbackItem => {
    const item = findItem(params.feedbackId ?? '')
    applyUpdate(item, body)
    return item
  }),
  route('GET', '/feedback/:feedbackId/media/:mediaId', ({ params }): Blob => {
    const blob = mediaBlobs.get(params.mediaId ?? '')
    if (!blob) notFound('Media')
    return blob
  }),
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
  route('POST', '/feedback/:feedbackId/media', ({ params, body }): FeedbackMedia => {
    const item = findItem(params.feedbackId ?? '')
    if (!(body instanceof FormData)) throw new ApiError(422, 'multipart/form-data body required')
    const file = body.get('file')
    const mediaType = body.get('media_type')
    if (!(file instanceof Blob) || !isMediaType(mediaType)) throw new ApiError(422, 'file and media_type are required')
    if (file.size > FEEDBACK_MAX_UPLOAD_BYTES) throw new ApiError(413, 'File too large. Maximum size is 10.0MB')
    if (mediaType === 'screenshot' && !isImageType(file.type)) throw new ApiError(400, 'Unsupported media format')
    if (mediaType === 'voice_note' && !isAudioType(file.type)) throw new ApiError(400, 'Unsupported media format')
    const media: FeedbackMedia = {
      id: `${fakeId(`media-${fixtureFeedbackMedia.length}`, 8)}-0000-4000-8000-${fakeId('md', 12)}`,
      feedback_id: item.id,
      media_type: mediaType,
      mime_type: file.type,
      file_name: file instanceof File ? file.name : null,
      file_size: file.size,
      created_at: new Date(FIXTURE_NOW).toISOString(),
    }
    fixtureFeedbackMedia.push(media)
    mediaBlobs.set(media.id, file)
    item.media_count += 1
    return media
  }),
]
