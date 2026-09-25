import { apiClient } from "./client";
import type { Repository, RepositoryCreate, IndexSummary, IndexingResponse } from "./types";

export const repositoriesApi = {
  /**
   * List all ingested repositories (sorted newest-first by backend).
   */
  list: (): Promise<Repository[]> =>
    apiClient.get<Repository[]>("/repositories"),

  /**
   * Get a single repository by ID.
   */
  get: (id: string): Promise<Repository> =>
    apiClient.get<Repository>(`/repositories/${id}`),

  /**
   * Ingest a new repository from a public GitHub URL and automatically trigger indexing.
   */
  create: (payload: RepositoryCreate): Promise<Repository> =>
    apiClient.post<Repository>("/repositories", { auto_index: true, ...payload }),

  /**
   * Manually trigger or re-run indexing on a repository.
   */
  index: (id: string): Promise<IndexingResponse> =>
    apiClient.post<IndexingResponse>(`/repositories/${id}/index`),

  /**
   * Delete a repository, its indexed files, chunks, and cloned directory.
   */
  delete: (id: string): Promise<void> =>
    apiClient.delete<void>(`/repositories/${id}`),

  /**
   * Get the indexing stats (files + chunks) for a repository.
   */
  getIndexSummary: (id: string): Promise<IndexSummary> =>
    apiClient.get<IndexSummary>(`/repositories/${id}/index`),
};
