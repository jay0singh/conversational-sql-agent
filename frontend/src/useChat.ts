// Chat state + send logic. Plain hooks, no state library (per spec).
//
// Step 8: sendMessage appends the user turn and a stubbed assistant reply —
// no backend call yet. Step 9 replaces the stub body with a streamed POST
// to /api/query, updating the pending assistant message as events arrive.

import { useRef, useState } from "react";
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

  async function sendMessage(question: string) {
    const trimmed = question.trim();
    if (!trimmed || busy) return;

    const userMsg: Message = { id: newId(), role: "user", text: trimmed };
    const assistantMsg: Message = {
      id: newId(),
      role: "assistant",
      text: "",
      pending: true,
    };
    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    setBusy(true);

    // --- STUB (step 8): no backend yet. Replaced by a streamed fetch in step 9.
    await new Promise((r) => setTimeout(r, 400));
    setMessages((prev) =>
      prev.map((m) =>
        m.id === assistantMsg.id
          ? {
              ...m,
              pending: false,
              text: `(backend not wired yet) You asked: "${trimmed}"`,
            }
          : m,
      ),
    );
    setBusy(false);
    // --- end stub
  }

  return { messages, busy, threadId: threadId.current, sendMessage, reset };
}
