import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, configureClient } from '../client'
import { fixtureFeedback, fixtureFeedbackMedia } from '../fixtures/feedback'
import { getFeatures } from './observability'
import { FEEDBACK_TYPES, createFeedback, getFeedbackStats, listFeedback, uploadFeedbackMedia, type FeedbackCreate } from './feedback'

const realFetch = globalThis.fetch
afterEach(() => {
  configureClient({ fixtures: false, fixtureLatencyMs: 120, fetch: (...a) => realFetch(...a) })
})

const body: FeedbackCreate = {
  url: 'http://localhost:5174/executions',
  route: '/executions',
  feedback_type: 'feature',
  comment: 'Title\n\nDescription',
  priority: 'medium',
  app_name: 'syn-ui',
}

describe('createFeedback', () => {
  it('POSTs the JSON body to /feedback and returns the created item', async () => {
    const item = { ...body, id: 'f-1', status: 'open', priority: 'medium', created_at: 'x', updated_at: 'x', media_count: 0 }
    const fetch = vi.fn(async () => new Response(JSON.stringify(item), { status: 201, headers: { 'Content-Type': 'application/json' } }))
    configureClient({ fetch, baseUrl: '/api/v1' })
    await expect(createFeedback(body)).resolves.toEqual(item)
    expect(fetch).toHaveBeenCalledWith('/api/v1/feedback', expect.objectContaining({ method: 'POST', body: JSON.stringify(body) }))
  })

  it('surfaces the 404 the API answers while the feature is off', async () => {
    configureClient({ fetch: async () => new Response(JSON.stringify({ detail: 'UI feedback is disabled' }), { status: 404 }) })
    await expect(createFeedback(body)).rejects.toMatchObject({ status: 404 })
  })

  it('lists every API FeedbackType once', () => {
    expect(new Set(FEEDBACK_TYPES).size).toBe(6)
  })
})

describe('feedback fixture', () => {
  it('answers like the API and stores the item', async () => {
    configureClient({ fixtures: true, fixtureLatencyMs: 0 })
    const before = fixtureFeedback.length
    const item = await createFeedback(body)
    expect(item).toMatchObject({ url: body.url, comment: body.comment, feedback_type: 'feature', status: 'open', priority: 'medium', media_count: 0 })
    expect(item.id).toMatch(/\S+/)
    expect(fixtureFeedback).toHaveLength(before + 1)
  })

  it('rejects a body without the required fields with a 422', async () => {
    configureClient({ fixtures: true, fixtureLatencyMs: 0 })
    const err = await createFeedback({ comment: 'x' } as FeedbackCreate).catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err).toMatchObject({ status: 422 })
  })

  it('turns the feature on in fixtures mode, so dev and e2e see the button', async () => {
    configureClient({ fixtures: true, fixtureLatencyMs: 0 })
    await expect(getFeatures()).resolves.toEqual({ ui_feedback: true })
  })
})

const PNG = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])

describe('uploadFeedbackMedia', () => {
  it('sends multipart file + media_type to /feedback/{id}/media', async () => {
    const fetch = vi.fn(async (_u: string | URL | Request, _i?: RequestInit) => new Response(JSON.stringify({ id: 'm-1' }), { status: 201 }))
    configureClient({ fetch, baseUrl: '/api/v1' })
    await uploadFeedbackMedia('f 1', new Blob([PNG], { type: 'image/png' }), 'screenshot', 'shot.png')
    const [url, init] = fetch.mock.calls[0]!
    expect(url).toBe('/api/v1/feedback/f%201/media')
    const form = init?.body
    expect(form).toBeInstanceOf(FormData)
    if (!(form instanceof FormData)) return
    expect(form.get('media_type')).toBe('screenshot')
    const file = form.get('file')
    expect(file).toBeInstanceOf(Blob)
    expect(file instanceof File ? file.name : '').toBe('shot.png')
  })
})

describe('feedback list and stats', () => {
  it('lists newest first for one app and counts open items', async () => {
    const fetch = vi.fn(async () => new Response(JSON.stringify({ items: [], total: 0, page: 1, page_size: 5 }), { status: 200 }))
    configureClient({ fetch, baseUrl: '/api/v1' })
    await listFeedback({ app: 'syn-ui', limit: 5 })
    expect(fetch).toHaveBeenCalledWith('/api/v1/feedback?app=syn-ui&limit=5&order_by=created_at&desc=true', expect.anything())
    await getFeedbackStats('syn-ui')
    expect(fetch).toHaveBeenLastCalledWith('/api/v1/feedback/stats?app=syn-ui', expect.anything())
  })
})

describe('feedback media fixture', () => {
  it('accepts a png for an existing item and bumps media_count', async () => {
    configureClient({ fixtures: true, fixtureLatencyMs: 0 })
    const item = await createFeedback({ ...body, app_name: 'syn-ui-media' })
    const media = await uploadFeedbackMedia(item.id, new Blob([PNG], { type: 'image/png' }), 'screenshot', 'shot.png')
    expect(media).toMatchObject({ feedback_id: item.id, media_type: 'screenshot', mime_type: 'image/png', file_name: 'shot.png' })
    expect(fixtureFeedbackMedia.at(-1)?.id).toBe(media.id)
    const list = await listFeedback({ app: 'syn-ui-media' })
    expect(list.items[0]).toMatchObject({ id: item.id, media_count: 1 })
    const s = await getFeedbackStats('syn-ui-media')
    expect(s.by_status?.open).toBe(1)
  })
  it('refuses a non-image screenshot and an unknown item', async () => {
    configureClient({ fixtures: true, fixtureLatencyMs: 0 })
    const item = await createFeedback(body)
    await expect(uploadFeedbackMedia(item.id, new Blob(['<svg/>'], { type: 'image/svg+xml' }), 'screenshot', 'x.svg')).rejects.toMatchObject({ status: 400 })
    await expect(uploadFeedbackMedia('nope', new Blob([PNG], { type: 'image/png' }), 'screenshot', 'x.png')).rejects.toMatchObject({ status: 404 })
  })
})
