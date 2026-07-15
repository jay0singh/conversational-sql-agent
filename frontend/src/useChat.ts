// Chat state + send logic. Plain hooks, no state library (per spec).
//
// Step 8: sendMessage appends the user turn and a stubbed assistant reply —
// no backend call yet. Step 9 replaces the stub body with a streamed POST
// to /api/query, updating the pending assistant message as events arrive.

import { useEffect, useRef, useState } from "react";
import { streamQuery, warmBackend } from "./api";
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

  // Start waking the (possibly asleep) free-tier backend as soon as the page
  // loads, so it's likely up by the time the user submits a question.
  useEffect(() => {
    warmBackend();
  }, []);

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

    // Retry early failures: a failed request before any event has streamed is
    // usually the free host still waking up (Render returns 404/502 during the
    // ~50s wake), so retry a few times before surfacing an error.
    const MAX_WAKE_RETRIES = 6;
    let attempt = 0;
    try {
      while (true) {
        let receivedAny = false;
        try {
          for await (const event of streamQuery(trimmed, threadId.current)) {
            receivedAny = true;
            if (event.type === "status") {
              patch(assistantId, { stage: event.stage, text: "" });
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
          break; // stream finished normally
        } catch (err) {
          if (!receivedAny && attempt < MAX_WAKE_RETRIES) {
            attempt += 1;
            patch(assistantId, {
              pending: true,
              stage: undefined,
              text: "Waking up the server — the free host sleeps when idle and can take up to a minute…",
            });
            await new Promise((r) => setTimeout(r, 5000));
            continue;
          }
          const message = err instanceof Error ? err.message : String(err);
          patch(assistantId, {
            pending: false,
            stage: undefined,
            text: `Couldn't reach the agent (${message}). It may still be waking up — try again in a moment.`,
          });
          break;
        }
      }
    } finally {
      setBusy(false);
    }
  }

  return { messages, busy, threadId: threadId.current, sendMessage, reset };
}
