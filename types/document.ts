export interface DocumentItem {
  id: string;
  filename: string;
  created_at: string | null;
}

export interface DeleteDocumentResponse {
  status: "deleted" | "partial_failure";
  document_id: string;
  db_deleted: boolean;
  garage_deleted: boolean;
  index_rebuilt: boolean;
  cache_invalidated: boolean;
  errors?: string[] | null;
  message: string;
}
