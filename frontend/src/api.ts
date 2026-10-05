import type { ChatResponse, DataOverview, GraphData, LLMProvider, ModelCatalog, VectorChunk } from "./types";

export async function sendChat(
  sessionId: string,
  message: string,
  llmProvider?: LLMProvider,
  llmModel?: string,
): Promise<ChatResponse> {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      message,
      llm_provider: llmProvider ?? null,
      llm_model: llmModel ?? null,
    }),
  });
  if (!res.ok) throw new Error(`Request failed (${res.status})`);
  return res.json();
}

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Request failed (${res.status})`);
  return res.json();
}

export const fetchModels = () => getJson<ModelCatalog>("/api/models");

export const fetchOverview = () => getJson<DataOverview>("/api/data/overview");

export const fetchChunks = (source: string | null, limit: number, offset: number) => {
  const q = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (source) q.set("source", source);
  return getJson<{ total: number; items: VectorChunk[] }>(`/api/data/vector/chunks?${q}`);
};

export const fetchGraph = () => getJson<GraphData>("/api/data/graph");
