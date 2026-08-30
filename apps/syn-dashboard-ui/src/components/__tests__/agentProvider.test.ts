import { describe, expect, it } from 'vitest'

import { agentProviderAccent, agentProviderLabel } from '../agentProvider'

/**
 * Claude and Codex badges both rendered in the accent blue, so a column of
 * badges read as one undifferentiated colour. Each harness gets its own hue.
 */
describe('agentProviderAccent', () => {
  it('gives Claude its own hue', () => {
    expect(agentProviderAccent('claude')).toBe('var(--color-agent-claude)')
  })

  it('keeps Codex on the accent blue', () => {
    expect(agentProviderAccent('codex')).toBe('var(--color-agent-codex)')
  })

  it('is case-insensitive, matching the label lookup', () => {
    expect(agentProviderAccent('CLAUDE')).toBe(agentProviderAccent('claude'))
  })

  it('falls back to the theme accent for an unknown provider', () => {
    expect(agentProviderAccent('gemini')).toBe('var(--color-accent)')
    expect(agentProviderAccent(null)).toBe('var(--color-accent)')
  })
})

describe('agentProviderLabel', () => {
  it('still names the known providers', () => {
    expect(agentProviderLabel('claude')).toBe('Claude')
    expect(agentProviderLabel('codex')).toBe('Codex')
  })
})
