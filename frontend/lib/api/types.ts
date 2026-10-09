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

export interface FileMetadata {
  path: string;
  size_bytes: number;
  extension: string;
}

export interface RepositoryFilesResponse {
  repository_id: string;
  total_files: number;
  files: FileMetadata[];
}

export interface FileContentResponse {
  repository_id: string;
  path: string;
  total_lines: number;
  size_bytes: number;
  content: string;
}

export interface ChunkRetrievalResult {
  chunk_id: string;
  file_id: string;
  path: string;
  content: string;
  start_line: number;
  end_line: number;
  similarity: number;
}

export interface SearchRequest {
  query: string;
  top_k?: number;
  similarity_threshold?: number | null;
}

export interface SearchResponse {
  repository_id: string;
  query: string;
  results: ChunkRetrievalResult[];
}

export interface Citation {
  path: string;
  start_line: number;
  end_line: number;
  file_path?: string;
}

export interface ChatRequest {
  question: string;
  message?: string;
}

export interface ChatResponse {
  answer: string;
  sources: Citation[];
}

export type KnowledgeStatus = "pending" | "processing" | "completed" | "failed";

export interface KnowledgeCreate {
  name: string;
  description?: string | null;
}

export interface KnowledgeDocument {
  id: string;
  knowledge_id: string;
  filename: string;
  source_type: string;
  file_size_bytes: number;
  status: KnowledgeStatus;
  error_message: string | null;
  chunks_count: number;
  created_at: string;
  updated_at: string;
}

export interface EngineeringKnowledge {
  id: string;
  name: string;
  description: string | null;
  status: KnowledgeStatus;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  documents: KnowledgeDocument[];
}

export type CodeScopeType = "repository" | "file";

export interface CodeScope {
  type: CodeScopeType;
  path?: string | null;
}

export interface KnowledgeAnalysisRequest {
  repository_id: string;
  knowledge_id: string;
  code_scope: CodeScope;
  question: string;
  top_k_repo?: number;
  top_k_knowledge?: number;
}

export interface AnalysisSource {
  source_id: string;
  type: "repository" | "knowledge";
  label: string;
  path: string;
  start_line?: number | null;
  end_line?: number | null;
  page_number?: number | null;
}

export interface AnalysisResponse {
  answer: string;
  sources: AnalysisSource[];
}
