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

export type LLMProvider = "anthropic" | "openai" | "ollama";

export interface ModelOption {
  id: string;
  label: string;
}

export interface ModelCatalog {
  providers: Record<LLMProvider, ModelOption[]>;
  default_provider: LLMProvider;
  default_model: string;
}

export interface Message {
  role: "user" | "assistant";
  text: string;
  citations?: Citation[];
  error?: boolean;
}

export interface SourceSummary {
  source: string;
  doc_type: string;
  chunks: number;
}

export interface DataOverview {
  vector: {
    available: boolean;
    error: string | null;
    collection: string;
    total_chunks: number;
    sources: SourceSummary[];
  };
  graph: {
    available: boolean;
    error: string | null;
    node_counts: Record<string, number>;
    relationship_counts: Record<string, number>;
  };
}

export interface VectorChunk {
  id: string;
  source: string;
  doc_type: string;
  heading: string;
  chunk_index: number;
  text: string;
}

export interface GraphNode {
  id: string;
  label: string;
  name: string;
  props: Record<string, string | number | boolean | null>;
}

export interface GraphEdge {
  type: string;
  source: string;
  target: string;
  role: string | null;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}
