import { apiClient } from "./client";
import type {
  KnowledgeAnalysisRequest,
  AnalysisResponse,
} from "./types";

export const analysisApi = {
  /**
   * Execute knowledge-guided code analysis using repository and engineering knowledge evidence.
   */
  analyze: (payload: KnowledgeAnalysisRequest): Promise<AnalysisResponse> =>
    apiClient.post<AnalysisResponse>("/analysis/knowledge", payload),
};
