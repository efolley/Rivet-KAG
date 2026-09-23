export interface Citation {
  id: string;
  source_type: "vector" | "graph";
  title: string;
  snippet: string;
  score: number | null;
}

export interface StageTrace {
  name: string;
  detail: string;
  duration_ms: number;
}

export interface ChatResponse {
  answer: string;
  citations: Citation[];
  trace: StageTrace[];
}

export interface Message {
  role: "user" | "assistant";
  text: string;
  citations?: Citation[];
  error?: boolean;
}
