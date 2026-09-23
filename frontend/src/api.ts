import type { ChatResponse } from "./types";

export async function sendChat(sessionId: string, message: string): Promise<ChatResponse> {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, message }),
  });
  if (!res.ok) throw new Error(`Request failed (${res.status})`);
  return res.json();
}
