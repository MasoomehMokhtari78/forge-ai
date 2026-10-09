import { apiClient } from "./client";
import type {
  EngineeringKnowledge,
  KnowledgeCreate,
  KnowledgeDocument,
} from "./types";

export const knowledgeApi = {
  /**
   * List all engineering knowledge scopes with their documents.
   */
  list: (): Promise<EngineeringKnowledge[]> =>
    apiClient.get<EngineeringKnowledge[]>("/knowledge"),

  /**
   * Retrieve a specific engineering knowledge scope by ID.
   */
  get: (id: string): Promise<EngineeringKnowledge> =>
    apiClient.get<EngineeringKnowledge>(`/knowledge/${id}`),

  /**
   * Create a new engineering knowledge scope.
   */
  create: (payload: KnowledgeCreate): Promise<EngineeringKnowledge> =>
    apiClient.post<EngineeringKnowledge>("/knowledge", payload),

  /**
   * Delete an engineering knowledge scope and all its documents/chunks.
   */
  delete: (id: string): Promise<void> =>
    apiClient.delete<void>(`/knowledge/${id}`),

  /**
   * Upload a PDF document into an engineering knowledge scope.
   */
  uploadDocument: (knowledgeId: string, file: File): Promise<KnowledgeDocument> => {
    const formData = new FormData();
    formData.append("file", file);
    return apiClient.upload<KnowledgeDocument>(
      `/knowledge/${knowledgeId}/documents`,
      formData
    );
  },

  /**
   * List documents belonging to an engineering knowledge scope.
   */
  listDocuments: (knowledgeId: string): Promise<KnowledgeDocument[]> =>
    apiClient.get<KnowledgeDocument[]>(`/knowledge/${knowledgeId}/documents`),

  /**
   * Delete a specific document from a knowledge scope.
   */
  deleteDocument: (knowledgeId: string, documentId: string): Promise<void> =>
    apiClient.delete<void>(`/knowledge/${knowledgeId}/documents/${documentId}`),
};
