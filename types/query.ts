export interface Source {
  section_id?: string;
  document_id?: string;
  heading?: string;
  node_type?: string;
  page?: number;
  path?: string;
  hit_node_id?: string;
  hit_node_type?: string;
  score?: number | null;
  role?: string;
}

export interface QueryResponse {
  answer: string;
  cached: boolean;
  sources: Source[];
  images: Record<string, unknown>[];
  context: string;
  flow: Record<string, Record<string, unknown>>;
  llm_skipped: boolean;
  query_plan: Record<string, unknown>;
  structured: Record<string, unknown>[];
}

export interface QueryHistoryItem {
  id: string;
  question: string;
  answer?: string | null;
  document_id?: string | null;
  sources?: Source[] | null;
  created_at: string;
}

export type StreamStatus = "idle" | "retrieving" | "generating" | "done" | "error";

export interface RetrievedEvent {
  event: "retrieved";
  cached: boolean;
  query_plan: Record<string, unknown>;
  sources: Source[];
  images: Record<string, unknown>[];
  structured: Record<string, unknown>[];
  context: string;
}

export interface TokenEvent {
  event: "token";
  text: string;
}

export interface DoneEvent extends QueryResponse {
  event: "done";
}

export interface ErrorEvent {
  event: "error";
  detail: string;
  request_id?: string;
}

export type StreamEvent = RetrievedEvent | TokenEvent | DoneEvent | ErrorEvent;
