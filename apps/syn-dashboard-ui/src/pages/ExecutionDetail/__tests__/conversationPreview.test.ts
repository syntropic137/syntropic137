import { expect, it } from 'vitest'
import { conversationPreview } from '../conversationPreview'

it('renders normalized messages in order and marks truncation', () => {
  const result = conversationPreview({
    supported: true,
    truncated: true,
    issues: [],
    messages: [
      { role: 'user', text: 'Spawn a child', line: 3 },
      { role: 'assistant', text: 'INVENTORY_CHILD_OK', line: 4 },
    ],
  })
  expect(result).toContain('USER\nSpawn a child\n\nASSISTANT\nINVENTORY_CHILD_OK')
  expect(result).toContain('Preview limited')
})

it('points to the download when no preview is available', () => {
  for (const value of [null, undefined, { supported: false, truncated: false, issues: ['unsupported_harness_conversation'], messages: [] }]) {
    expect(conversationPreview(value)).toContain('Download the verified archive')
  }
})
