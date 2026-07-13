import { useEffect, useRef, useState } from "react";
import { useChat } from "./useChat";
import type { Stage } from "./types";
import "./App.css";

const EXAMPLES = [
  "Who won the 2021 drivers' championship?",
  "Top 3 drivers by race wins in 2023",
  "How many races has Lewis Hamilton won since 2010?",
];

const STAGE_LABELS: Record<Stage, string> = {
  generating: "Generating SQL…",
  validating: "Validating…",
  executing: "Running query…",
};

export default function App() {
  const { messages, busy, sendMessage, reset } = useChat();
  const [input, setInput] = useState("");
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    sendMessage(input);
    setInput("");
  }

  return (
    <div className="app">
      <header className="header">
        <h1>🏎️ F1 SQL Agent</h1>
        <button className="reset" onClick={reset} disabled={busy}>
          New chat
        </button>
      </header>

      <main className="messages">
        {messages.length === 0 && (
          <div className="empty">
            <p>Ask a question about Formula 1 (2010–present).</p>
            <div className="examples">
              {EXAMPLES.map((ex) => (
                <button key={ex} className="example" onClick={() => sendMessage(ex)}>
                  {ex}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m) => (
          <div key={m.id} className={`msg ${m.role}`}>
            <div className="bubble">
              {m.pending ? (
                <span className="typing">{m.stage ? STAGE_LABELS[m.stage] : "…"}</span>
              ) : (
                m.text
              )}
            </div>
          </div>
        ))}
        <div ref={endRef} />
      </main>

      <form className="composer" onSubmit={submit}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about F1 races, drivers, standings…"
          disabled={busy}
          autoFocus
        />
        <button type="submit" disabled={busy || !input.trim()}>
          Send
        </button>
      </form>
    </div>
  );
}
