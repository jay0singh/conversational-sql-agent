import { useEffect, useRef, useState } from "react";
import { useChat } from "./useChat";
import { ResultView } from "./ResultView";
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

// Original racing-style wordmark (speed streaks + italic F1) — deliberately not
// the trademarked Formula 1 logo.
function Logo() {
  return (
    <svg width="52" height="24" viewBox="0 0 52 24" role="img" aria-label="F1" className="logo">
      <g fill="var(--accent)">
        <rect x="0" y="3" width="9" height="3" transform="skewX(-20)" opacity="0.45" />
        <rect x="0" y="10" width="15" height="3" transform="skewX(-20)" opacity="0.7" />
        <rect x="0" y="17" width="9" height="3" transform="skewX(-20)" opacity="0.45" />
      </g>
      <text
        x="19"
        y="20"
        fontFamily="system-ui, sans-serif"
        fontSize="22"
        fontWeight="800"
        fontStyle="italic"
        fill="var(--accent)"
      >
        F1
      </text>
    </svg>
  );
}

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
        <h1>
          <Logo />
          <span>SQL Agent</span>
        </h1>
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

        {messages.map((m) => {
          const hasResult = !m.pending && m.result && !m.result.failure;
          return (
            <div key={m.id} className={`msg ${m.role}`}>
              <div className={`bubble${hasResult ? " has-result" : ""}`}>
                {m.pending ? (
                  <span className="typing">{m.stage ? STAGE_LABELS[m.stage] : "…"}</span>
                ) : (
                  m.text
                )}
                {hasResult && <ResultView result={m.result!} />}
              </div>
            </div>
          );
        })}
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
