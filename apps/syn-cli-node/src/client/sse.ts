import { SynClient } from "./http.js";

export interface SSEEvent {
  type: string;
  data?: Record<string, unknown>;
  timestamp?: string;
  event_type?: string;
}

export function parseSseLine(line: string): SSEEvent | null {
  if (!line.startsWith("data: ")) return null;
  const raw = line.slice(6).trim();
  if (!raw) return null;
  try {
    return JSON.parse(raw) as SSEEvent;
  } catch {
    return null;
  }
}

export async function* streamSSE(path: string): AsyncGenerator<SSEEvent, void, void> {
  const client = new SynClient();
  const body = await client.stream(path);
  const reader = body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += value;
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) continue;
        const event = parseSseLine(trimmed);
        if (event) yield event;
      }
    }

    if (buffer.trim()) {
      const event = parseSseLine(buffer.trim());
      if (event) yield event;
    }
  } finally {
    reader.releaseLock();
  }
}
