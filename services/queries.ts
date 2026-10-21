import type { QueryHistoryItem, QueryResponse, StreamEvent } from "@/types/query";
import { apiUrl, authHeaders, readError } from "@/services/api";
import { consumeSseFrames, flushSseBuffer } from "@/utils/sse";

export async function askQuestion(question: string, documentId?: string): Promise<QueryResponse> {
  const response = await fetch(apiUrl("/query"), {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({
      question,
      document_id: documentId || undefined,
    }),
  });
  if (!response.ok) {
    throw new Error(await readError(response, "Query failed"));
  }
  const data = (await response.json()) as QueryResponse;
  return data;
}

export async function streamQuestion(
  question: string,
  documentId: string | undefined,
  onEvent: (event: StreamEvent) => void,
): Promise<void> {
  const response = await fetch(apiUrl("/query/stream"), {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({
      question,
      document_id: documentId || undefined,
    }),
  });
  if (!response.ok) {
    throw new Error(await readError(response, "Stream request failed"));
  }
  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error("Response body is not readable");
  }
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parsed = consumeSseFrames(buffer);
    buffer = parsed.rest;
    for (const event of parsed.events) onEvent(event as StreamEvent);
  }
  buffer += decoder.decode();
  for (const event of flushSseBuffer(buffer)) onEvent(event as StreamEvent);
}

export async function listQueryHistory(): Promise<QueryHistoryItem[]> {
  const response = await fetch(apiUrl("/query-history"), {
    headers: authHeaders(),
  });
  if (!response.ok) {
    throw new Error(await readError(response, "Failed to fetch query history"));
  }
  const data = (await response.json()) as { history?: QueryHistoryItem[] };
  return data.history ?? [];
}

export async function deleteQueryHistory(queryId: string): Promise<void> {
  const response = await fetch(apiUrl(`/query-history/${queryId}`), {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!response.ok) {
    throw new Error(await readError(response, "Delete failed"));
  }
}
