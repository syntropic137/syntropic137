import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, configureClient } from '../client'
import { fixtureFeedback } from '../fixtures/feedback'
import { getFeatures } from './observability'
import { FEEDBACK_TYPES, createFeedback, type FeedbackCreate } from './feedback'

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
