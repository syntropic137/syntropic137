import type { LocalTranscript } from '../../api/sessionInventory'

type Conversation = NonNullable<LocalTranscript['conversation']>

const NOTICE = '\n\n[Preview limited. Download contains the complete archive.]'
const UNAVAILABLE = 'No conversation preview for this transcript. Download the verified archive to inspect it.'

/** Renders the API's normalized conversation. Never inspects archive bytes or harness formats. */
export function conversationPreview(conversation: Conversation | null | undefined): string {
  if (!conversation?.supported || conversation.messages.length === 0) return UNAVAILABLE
  const body = conversation.messages.map(message => `${message.role.toUpperCase()}\n${message.text}`).join('\n\n')
  return 'Conversation preview (may include inherited history)\n\n' + body + (conversation.truncated ? NOTICE : '')
}
