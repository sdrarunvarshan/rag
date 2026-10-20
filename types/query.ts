export interface QueryHistoryItem {
  id: string;
  question: string;
  answer?: string | null;
  document_id?: string | null;
  sources?: unknown[] | null;
  created_at: string;
}

export type StreamStatus = "idle" | "retrieving" | "generating" | "done" | "error";

export interface StreamEvent {
  event: "retrieved" | "token" | "done" | "error";
  text?: string;
  answer?: string;
  detail?: string;
  sources?: unknown[];
}
