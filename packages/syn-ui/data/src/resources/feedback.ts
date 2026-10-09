/**
 * In-app feedback (lib/ui-feedback, ADR-016, #1385): create, the recent list
 * and open count the bubble shows, and the multipart screenshot upload.
 * Update/delete stay in the React widget's tickets view.
 *
 * The routes exist only on an API built with the feedback extra, and answer
 * 404 while SYN_UI_FEEDBACK_ENABLED is off. Gate the UI on `getFeatures()`.
 */
import { clientConfig, request, requestForm, usingFixtures } from '../client'
import type { components } from '../generated/api-types'

export type FeedbackCreate = components['schemas']['FeedbackCreate']
export type FeedbackItem = components['schemas']['FeedbackItem']
export type FeedbackType = components['schemas']['FeedbackType']
export type FeedbackPriority = components['schemas']['Priority']
export type FeedbackStatus = components['schemas']['Status']
export type FeedbackSubjectKind = components['schemas']['SubjectKind']
export type FeedbackList = components['schemas']['FeedbackList']
export type FeedbackStats = components['schemas']['FeedbackStats']
export type FeedbackMediaType = components['schemas']['MediaType']
export type FeedbackMedia = components['schemas']['MediaItem']

/** The backend's per-file ceiling (UI_FEEDBACK_MAX_FILE_SIZE / the host's MAX_UPLOAD_BYTES default). */
export const FEEDBACK_MAX_UPLOAD_BYTES = 10 * 1024 * 1024
/** Screenshot formats the media route accepts (it checks the magic bytes too). */
export const FEEDBACK_IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/webp'] as const

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

export interface FeedbackListQuery {
  app?: string
  status?: FeedbackStatus
  limit?: number
  page?: number
}

/** Newest first. Not cached: the bubble reads it once per open. */
export function listFeedback(q: FeedbackListQuery = {}, signal?: AbortSignal): Promise<FeedbackList> {
  return request('/feedback', { query: { app: q.app, status: q.status, limit: q.limit, page: q.page, order_by: 'created_at', desc: true }, signal, coalesce: false })
}

/** Counts by status/type/priority, optionally for one app (the bubble's open badge). */
export function getFeedbackStats(app?: string, signal?: AbortSignal): Promise<FeedbackStats> {
  return request('/feedback/stats', { query: { app }, signal, coalesce: false })
}

/** Attach one file to an item: multipart `file` + `media_type`, as POST /feedback/{id}/media expects. */
export function uploadFeedbackMedia(feedbackId: string, file: Blob, mediaType: FeedbackMediaType, fileName: string, signal?: AbortSignal): Promise<FeedbackMedia> {
  const form = new FormData()
  form.append('file', file, fileName)
  form.append('media_type', mediaType)
  return requestForm(`/feedback/${encodeURIComponent(feedbackId)}/media`, form, { signal })
}

export type FeedbackItemWithMedia = components['schemas']['FeedbackItemWithMedia']
export type FeedbackUpdate = components['schemas']['FeedbackUpdate']

/** One item with its media list (no bytes). */
export function getFeedback(feedbackId: string, signal?: AbortSignal): Promise<FeedbackItemWithMedia> {
  return request(`/feedback/${encodeURIComponent(feedbackId)}`, { signal, coalesce: false })
}

/** PATCH status, priority, assignee, notes or comment; returns the updated item. */
export function updateFeedback(feedbackId: string, body: FeedbackUpdate, signal?: AbortSignal): Promise<FeedbackItem> {
  return request(`/feedback/${encodeURIComponent(feedbackId)}`, { method: 'PATCH', body, signal })
}

/**
 * A URL an <img> can load for one media item: the API route itself, or in
 * fixtures mode an object URL for the stored upload (fixtures have no
 * server to serve bytes). The caller revokes `blob:` URLs it no longer shows.
 */
export async function feedbackMediaSrc(feedbackId: string, mediaId: string, signal?: AbortSignal): Promise<string> {
  if (!usingFixtures()) return `${clientConfig().baseUrl}/feedback/${encodeURIComponent(feedbackId)}/media/${encodeURIComponent(mediaId)}`
  const blob = await request<Blob>(`/feedback/${encodeURIComponent(feedbackId)}/media/${encodeURIComponent(mediaId)}`, { signal, coalesce: false })
  return URL.createObjectURL(blob)
}
