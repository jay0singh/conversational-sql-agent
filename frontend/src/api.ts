// Streaming client for POST /api/query.
//
// The browser's EventSource only does GET, so we POST via fetch and read the
// response body as a stream, splitting the `data: {...}\n\n` SSE frames and
// yielding each parsed event as it arrives.

import type { AgentEvent } from "./types";

// Dev: the Vite proxy maps /api -> the backend (stripping /api). Production:
// FastAPI serves this app from its own origin, so the API is at the root.
const API_BASE = import.meta.env.DEV ? "/api" : "";

// Stateful frame splitter: bytes arrive in arbitrary chunks, so a single SSE
// frame can span two reads. push() buffers and returns whatever frames are now
// complete. Extracted so it can be unit-tested without a real network stream.
export class SSEBuffer {
  private buffer = "";

  push(chunk: string): AgentEvent[] {
    this.buffer += chunk;
    const events: AgentEvent[] = [];
    let sep: number;
    while ((sep = this.buffer.indexOf("\n\n")) !== -1) {
      const frame = this.buffer.slice(0, sep).trim();
      this.buffer = this.buffer.slice(sep + 2);
      if (frame.startsWith("data:")) {
        events.push(JSON.parse(frame.slice(frame.indexOf(":") + 1).trim()) as AgentEvent);
      }
    }
    return events;
  }
}

// Free hosts (Render) sleep when idle and take ~50s to wake. Pinging health on
// page load starts the wake early, so the server is usually up by the time the
// user submits their first question. Fire-and-forget.
export function warmBackend(): void {
  fetch(`${API_BASE}/health`).catch(() => {});
}

export async function* streamQuery(
  question: string,
  threadId: string,
): AsyncGenerator<AgentEvent> {
  const res = await fetch(`${API_BASE}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, thread_id: threadId }),
  });
  if (!res.ok || !res.body) {
    throw new Error(`request failed (${res.status})`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  const sse = new SSEBuffer();

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    for (const event of sse.push(decoder.decode(value, { stream: true }))) {
      yield event;
    }
  }
}
