// Chat state + send logic. Plain hooks, no state library (per spec).
//
// Step 8: sendMessage appends the user turn and a stubbed assistant reply —
// no backend call yet. Step 9 replaces the stub body with a streamed POST
// to /api/query, updating the pending assistant message as events arrive.

import { useRef, useState } from "react";
import { streamQuery } from "./api";
import type { Message } from "./types";

function newId(): string {
  return crypto.randomUUID();
}

export function useChat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [busy, setBusy] = useState(false);
  // One thread_id per browser session, generated client-side so the backend
  // maintains conversation memory across turns.
  const threadId = useRef<string>(crypto.randomUUID());

  function reset() {
    setMessages([]);
    threadId.current = crypto.randomUUID();
  }

  function patch(id: string, changes: Partial<Message>) {
    setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, ...changes } : m)));
  }

  async function sendMessage(question: string) {
    const trimmed = question.trim();
    if (!trimmed || busy) return;

    const userMsg: Message = { id: newId(), role: "user", text: trimmed };
    const assistantId = newId();
    setMessages((prev) => [
      ...prev,
      userMsg,
      { id: assistantId, role: "assistant", text: "", pending: true },
    ]);
    setBusy(true);

    try {
      for await (const event of streamQuery(trimmed, threadId.current)) {
        if (event.type === "status") {
          patch(assistantId, { stage: event.stage });
        } else if (event.type === "result") {
          patch(assistantId, {
            pending: false,
            stage: undefined,
            text: event.summary ?? "(no answer produced)",
            result: {
              sql: event.sql,
              columns: event.columns,
              rows: event.rows,
              summary: event.summary,
              failure: event.failure,
              attempts: event.attempts,
            },
          });
        } else {
          patch(assistantId, { pending: false, stage: undefined, text: `Error: ${event.message}` });
        }
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      patch(assistantId, {
        pending: false,
        stage: undefined,
        text: `Could not reach the agent (${message}). Is the backend running?`,
      });
    } finally {
      setBusy(false);
    }
  }

  return { messages, busy, threadId: threadId.current, sendMessage, reset };
}
