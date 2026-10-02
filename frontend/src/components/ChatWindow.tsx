import { useEffect, useRef, useState } from "react";
import { fetchModels, sendChat } from "../api";
import type { LLMProvider, Message, ModelCatalog, ModelOption } from "../types";
import Citations from "./Citations";

const sessionId = crypto.randomUUID();

// Pulls back both a vector match (expense_policy.md) and a graph match (the Document node's
// OWNS_DOC relationship), so it's a good one-click demo of the pipeline querying both stores.
const SUGGESTED_QUESTION = "What is the meal expense limit while travelling?";

const PROVIDER_LABEL: Record<LLMProvider, string> = { anthropic: "Anthropic", openai: "OpenAI", ollama: "Ollama" };

export default function ChatWindow() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null);
  const [provider, setProvider] = useState<LLMProvider | null>(null);
  const [model, setModel] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  useEffect(() => {
    fetchModels()
      .then((c) => {
        setCatalog(c);
        setProvider(c.default_provider);
        setModel(c.default_model);
      })
      .catch(() => {
        /* model picker just won't render; chat still works against the server default */
      });
  }, []);

  function onProviderChange(next: LLMProvider) {
    setProvider(next);
    setModel(catalog?.providers[next][0]?.id ?? null);
  }

  async function submit() {
    const text = input.trim();
    if (!text || loading) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", text }]);
    setLoading(true);
    try {
      const res = await sendChat(sessionId, text, provider ?? undefined, model ?? undefined);
      setMessages((m) => [...m, { role: "assistant", text: res.answer, citations: res.citations }]);
    } catch (e) {
      setMessages((m) => [...m, { role: "assistant", text: (e as Error).message, error: true }]);
    } finally {
      setLoading(false);
    }
  }

  const modelOptions: ModelOption[] = provider && catalog ? catalog.providers[provider] : [];

  return (
    <main className="chat">
      {catalog && provider && (
        <div className="model-picker">
          <label>
            Provider
            <select value={provider} onChange={(e) => onProviderChange(e.target.value as LLMProvider)}>
              {(Object.keys(catalog.providers) as LLMProvider[]).map((p) => (
                <option key={p} value={p}>
                  {PROVIDER_LABEL[p]}
                </option>
              ))}
            </select>
          </label>
          <label>
            Model
            <select value={model ?? ""} onChange={(e) => setModel(e.target.value)}>
              {modelOptions.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label}
                </option>
              ))}
            </select>
          </label>
        </div>
      )}
      <div className="messages">
        {messages.length === 0 && (
          <div className="empty">
            <p>Ask a question about your data. Try one that uses both sources:</p>
            <button type="button" className="suggestion" onClick={() => setInput(SUGGESTED_QUESTION)}>
              “{SUGGESTED_QUESTION}”
            </button>
          </div>
        )}
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
