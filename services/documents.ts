import type { DocumentItem } from "@/types/document";
import { apiUrl, authHeaders, readError } from "@/services/api";

export async function listDocuments(): Promise<DocumentItem[]> {
  const response = await fetch(apiUrl("/documents"), {
    headers: authHeaders(),
  });
  if (!response.ok) {
    throw new Error(await readError(response, "Failed to fetch documents"));
  }
  const data = (await response.json()) as { documents?: DocumentItem[] };
  return data.documents ?? [];
}

export async function uploadDocument(file: File): Promise<void> {
  const formData = new FormData();
  formData.append("file", file);
  const response = await fetch(apiUrl("/ingest"), {
    method: "POST",
    headers: authHeaders(),
    body: formData,
  });
  if (!response.ok) {
    throw new Error(await readError(response, "Upload failed"));
  }
}

export async function deleteDocument(documentId: string): Promise<void> {
  const response = await fetch(apiUrl(`/documents/${documentId}`), {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!response.ok) {
    throw new Error(await readError(response, "Delete failed"));
  }
}
