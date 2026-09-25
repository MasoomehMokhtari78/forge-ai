/**
 * ForgeAI API types — matches the actual backend Pydantic schemas exactly.
 * Do not add fields that don't exist in the backend.
 */

export type IngestionStatus = "pending" | "processing" | "completed" | "failed";

export interface Repository {
  id: string;
  url: string;
  name: string;
  status: IngestionStatus;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  ingested_at: string | null;
}

export interface RepositoryCreate {
  url: string;
  auto_index?: boolean;
}

export interface IndexSummary {
  repository_id: string;
  files_indexed: number;
  chunks_created: number;
}

export interface IndexingResponse {
  repository_id: string;
  status: string;
  files_indexed: number;
  chunks_created: number;
}

export interface ApiError {
  detail: string;
}
