// Streaming client for POST /api/query.
//
// The browser's EventSource only does GET, so we POST via fetch and read the
// response body as a stream, splitting the `data: {...}\n\n` SSE frames and
// yielding each parsed event as it arrives.

import type { AgentEvent } from "./types";

export async function* streamQuery(
  question: string,
  threadId: string,
): AsyncGenerator<AgentEvent> {
  const res = await fetch("/api/query", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, thread_id: threadId }),
  });
  if (!res.ok || !res.body) {
    throw new Error(`request failed (${res.status})`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, sep).trim();
      buffer = buffer.slice(sep + 2);
      if (frame.startsWith("data:")) {
        yield JSON.parse(frame.slice(frame.indexOf(":") + 1).trim()) as AgentEvent;
      }
    }
  }
}
