import { SSE_CONNECT_TIMEOUT_MS, getApiUrl, getAuthHeaders } from "../config.js";

const API_PREFIX = (process.env["SYN_NO_PREFIX"] === "1" || process.env["SYN_NO_PREFIX"] === "true") ? "" : "/api/v1";

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

async function fetchStream(path: string): Promise<ReadableStream<Uint8Array>> {
  const base = new URL(getApiUrl());
  const basePath = base.pathname.replace(/\/+$/, "");
  const prefix = basePath.endsWith(API_PREFIX) ? "" : API_PREFIX;
  const reqPath = path.startsWith("/") ? path : `/${path}`;
  const url = new URL(`${basePath}${prefix}${reqPath}`, base);

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), SSE_CONNECT_TIMEOUT_MS);

  const response = await fetch(url.toString(), {
    method: "GET",
    headers: getAuthHeaders(),
    signal: controller.signal,
  });

  clearTimeout(timer);

  if (!response.body) {
    throw new Error("Response body is null");
  }

  return response.body;
}

export async function* streamSSE(path: string): AsyncGenerator<SSEEvent, void, void> {
  const body = await fetchStream(path);
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
