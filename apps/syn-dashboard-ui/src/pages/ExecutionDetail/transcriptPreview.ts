const LIMIT = 32768
const NOTICE = '\n[Preview limited to 32K characters. Download contains the complete archive.]'

type ObjectValue = Record<string, unknown>
function object(value: unknown): ObjectValue | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as ObjectValue : null
}

function messageText(value: unknown): string | null {
  const message = object(value)
  if (!message || (message.role !== 'user' && message.role !== 'assistant')) return null
  const content = message.content
  const text = typeof content === 'string' ? content : Array.isArray(content)
    ? content.map(part => object(part)?.text).filter((part): part is string => typeof part === 'string').join('\n') : ''
  return text ? `${message.role.toUpperCase()}\n${text}` : null
}

function unwrapArchive(text: string): string {
  try {
    const envelope = object(JSON.parse(text))
    return typeof envelope?.raw === 'string' ? envelope.raw : text
  } catch { return text }
}

function readMessage(line: string): string | null {
  try {
    const row = object(JSON.parse(line))
    const payload = object(row?.payload)
    const value = row?.type === 'response_item' && payload?.type === 'message' ? payload : row?.message
    return messageText(value)
  } catch { return null }
}

function conversation(raw: string): string {
  const messages: string[] = []
  let size = 0
  for (const line of raw.split('\n')) {
    const message = readMessage(line)
    if (!message) continue
    messages.push(message)
    size += message.length + 2
    if (size > LIMIT) break
  }
  return messages.length ? 'Conversation preview (may include inherited history)\n\n' + messages.join('\n\n') : raw
}

/** Conversation excerpt only. The verified download always retains every source byte. */
export function transcriptPreview(bytes: Uint8Array): string {
  let text: string
  try { text = new TextDecoder('utf-8', { fatal: true }).decode(bytes) }
  catch { return 'Binary transcript. Download the verified archive to inspect it.' }
  const preview = conversation(unwrapArchive(text))
  return preview.slice(0, LIMIT) + (preview.length > LIMIT ? NOTICE : '')
}
