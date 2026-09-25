import { expect, it } from 'vitest'
import { transcriptPreview } from '../transcriptPreview'
const bytes = (value: string) => new TextEncoder().encode(value)

it('shows conversation after a large Codex header without rendering developer instructions', () => {
  const raw = [
    { type: 'session_meta', payload: { instructions: 'x'.repeat(50000) } },
    { type: 'response_item', payload: { type: 'message', role: 'developer', content: 'internal' } },
    { type: 'response_item', payload: { type: 'message', role: 'user', content: [{ text: 'Spawn a child' }] } },
    { type: 'response_item', payload: { type: 'message', role: 'assistant', content: [{ text: 'INVENTORY_CHILD_OK' }] } },
  ].map(row => JSON.stringify(row)).join('\n')
  const result = transcriptPreview(bytes(JSON.stringify({ raw })))
  expect(result).toContain('USER\nSpawn a child')
  expect(result).toContain('ASSISTANT\nINVENTORY_CHILD_OK')
  expect(result).not.toContain('internal')
  expect(result.length).toBeLessThan(300)
})

it('supports native Claude messages and tolerates malformed records', () => {
  expect(transcriptPreview(bytes('bad\n' + JSON.stringify({ message: { role: 'assistant', content: [{ text: 'hello' }] } })))).toContain('ASSISTANT\nhello')
})

it('keeps unsupported text visible and bounds oversized previews', () => {
  expect(transcriptPreview(bytes('<script>text only</script>'))).toBe('<script>text only</script>')
  const result = transcriptPreview(bytes('x'.repeat(40000)))
  expect(result).toContain('Preview limited')
  expect(result.length).toBeLessThan(33000)
})

it('handles invalid UTF-8 without substituting misleading text', () => {
  expect(transcriptPreview(new Uint8Array([255]))).toContain('Binary transcript')
})
