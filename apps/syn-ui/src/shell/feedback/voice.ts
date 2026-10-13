/**
 * Voice notes, as the React widget records them (ui-feedback-react
 * useVoiceRecorder + mediaRecorderSetup): one note per item, MediaRecorder
 * with the first supported of webm/opus, webm, ogg/opus, mp4, 100 ms chunks,
 * uploaded as media_type `voice_note` (`voice-note-<ms>.webm`) through the
 * same multipart route as screenshots. No transcription, there or here.
 */
export const VOICE_MIME_PREFERENCE = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4'] as const

export function voiceSupported(): boolean {
  return typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== 'undefined'
}

export function supportedVoiceMime(): string | undefined {
  return VOICE_MIME_PREFERENCE.find((t) => MediaRecorder.isTypeSupported(t))
}

/** `0:07` */
export function formatDuration(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

export function voiceError(err: unknown): string {
  if (err instanceof DOMException && (err.name === 'NotAllowedError' || err.name === 'SecurityError')) return 'Microphone permission denied. Allow it in the browser to record.'
  if (err instanceof DOMException && err.name === 'NotFoundError') return 'No microphone found.'
  return 'Could not start recording.'
}

export interface VoiceNote {
  blob: Blob
  url: string
  seconds: number
}

/** Extension for the upload's file name, from the recorded MIME type. */
export function voiceFileName(mime: string, now = Date.now()): string {
  const ext = mime.startsWith('audio/ogg') ? 'ogg' : mime.startsWith('audio/mp4') ? 'm4a' : 'webm'
  return `voice-note-${now}.${ext}`
}
