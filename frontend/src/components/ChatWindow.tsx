import { useEffect, useRef, useState } from "react";
import { sendChat } from "../api";
import type { Message } from "../types";
import Citations from "./Citations";

const sessionId = crypto.randomUUID();

export default function ChatWindow() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  async function submit() {
    const text = input.trim();
    if (!text || loading) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", text }]);
    setLoading(true);
    try {
      const res = await sendChat(sessionId, text);
      setMessages((m) => [...m, { role: "assistant", text: res.answer, citations: res.citations }]);
    } catch (e) {
      setMessages((m) => [...m, { role: "assistant", text: (e as Error).message, error: true }]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="chat">
      <div className="messages">
        {messages.length === 0 && <p className="empty">Ask a question about your data.</p>}
        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.role}${m.error ? " error" : ""}`}>
            {m.role === "assistant" && !m.error ? (
              <>
                <h4 className="section-title">Answer</h4>
                <p>{m.text}</p>
                {m.citations && m.citations.length > 0 && (
                  <div className="citation-chips">
                    {m.citations.map((c, ci) => (
                      <span key={c.id} className={`chip-ref ${c.source_type}`}>
                        [{ci + 1}] {c.title}
                      </span>
                    ))}
                  </div>
                )}
                {m.citations && m.citations.length > 0 && (
                  <>
                    <h4 className="section-title">Context</h4>
                    <Citations items={m.citations} />
                  </>
                )}
              </>
            ) : (
              <p>{m.text}</p>
            )}
          </div>
        ))}
        {loading && <div className="msg assistant">Thinking…</div>}
        <div ref={endRef} />
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          placeholder="Type your question…"
          rows={2}
        />
        <button type="submit" disabled={loading || !input.trim()}>
          Send
        </button>
      </form>
    </main>
  );
}
