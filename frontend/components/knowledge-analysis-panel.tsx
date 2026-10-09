"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";
import {
  BookOpen,
  FileCode2,
  FolderGit2,
  Send,
  AlertCircle,
  Loader2,
  FileText,
  ArrowRight,
  ExternalLink,
  RotateCcw,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { MarkdownRenderer } from "@/components/markdown-renderer";
import { knowledgeApi } from "@/lib/api/knowledge";
import { analysisApi } from "@/lib/api/analysis";
import { ApiClientError } from "@/lib/api/client";
import { useToast } from "@/components/ui/toast";
import type {
  Repository,
  FileMetadata,
  EngineeringKnowledge,
  AnalysisResponse,
  CodeScopeType,
} from "@/lib/api/types";

interface KnowledgeAnalysisPanelProps {
  repository: Repository;
  files: FileMetadata[];
  activeFilePath?: string | null;
  onSelectFile: (path: string, line?: number) => void;
  className?: string;
}

export function KnowledgeAnalysisPanel({
  repository,
  files,
  activeFilePath = null,
  onSelectFile,
  className = "",
}: KnowledgeAnalysisPanelProps) {
  const toast = useToast();
  // Knowledge scopes state
  const [scopes, setScopes] = useState<EngineeringKnowledge[]>([]);
  const [isLoadingScopes, setIsLoadingScopes] = useState<boolean>(true);
  const [selectedKnowledgeId, setSelectedKnowledgeId] = useState<string>("");

  // Code scope state: "repository" | "file"
  const [codeScopeType, setCodeScopeType] = useState<CodeScopeType>(
    activeFilePath ? "file" : "repository"
  );
  const [selectedPath, setSelectedPath] = useState<string>(activeFilePath || (files[0]?.path ?? ""));

  // Question & analysis state
  const [question, setQuestion] = useState<string>("");
  const [isAnalyzing, setIsAnalyzing] = useState<boolean>(false);
  const [result, setResult] = useState<AnalysisResponse | null>(null);

  // Sync activeFilePath if changed from outside
  const [prevActiveFilePath, setPrevActiveFilePath] = useState(activeFilePath);
  if (activeFilePath !== prevActiveFilePath) {
    setPrevActiveFilePath(activeFilePath);
    if (activeFilePath) {
      setSelectedPath(activeFilePath);
    }
  }

  // Fetch knowledge scopes
  useEffect(() => {
    let ignore = false;
    knowledgeApi
      .list()
      .then((data) => {
        if (ignore) return;
        setScopes(data);
        if (data.length > 0 && !selectedKnowledgeId) {
          // Default to first completed scope, or first scope
          const completedScope = data.find((s) => s.status === "completed") || data[0];
          setSelectedKnowledgeId(completedScope.id);
        }
      })
      .catch((err) => {
        if (ignore) return;
        const msg =
          err instanceof ApiClientError ? err.detail ?? err.message : "Failed to load knowledge scopes.";
        toast.error(msg, "Error Loading Scopes");
      })
      .finally(() => {
        if (!ignore) setIsLoadingScopes(false);
      });

    return () => {
      ignore = true;
    };
  }, [selectedKnowledgeId, toast]);

  const selectedScope = scopes.find((s) => s.id === selectedKnowledgeId);
  const completedDocsCount =
    selectedScope?.documents?.filter((d) => d.status === "completed").length ?? 0;

  const handleRunAnalysis = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const cleanQuestion = question.trim();
    if (!cleanQuestion || !selectedKnowledgeId || isAnalyzing) return;

    if (codeScopeType === "file" && !selectedPath) {
      const msg = "Please select a file to analyze.";
      toast.warning(msg, "File Required");
      return;
    }

    setIsAnalyzing(true);

    try {
      const response = await analysisApi.analyze({
        repository_id: repository.id,
        knowledge_id: selectedKnowledgeId,
        code_scope: {
          type: codeScopeType,
          path: codeScopeType === "file" ? selectedPath : null,
        },
        question: cleanQuestion,
      });
      setResult(response);
      toast.success("Analysis generated with grounded citations.", "Analysis Completed");
    } catch (err) {
      const msg =
        err instanceof ApiClientError
          ? err.detail ?? err.message
          : err instanceof Error
          ? err.message
          : "An unexpected error occurred during analysis.";
      toast.error(msg, "Analysis Failed");
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleReset = () => {
    setResult(null);
  };

  // Group sources by domain
  const repoSources = result?.sources.filter((s) => s.type === "repository") ?? [];
  const knowledgeSources = result?.sources.filter((s) => s.type === "knowledge") ?? [];

  return (
    <div
      className={`flex flex-col h-full overflow-hidden bg-background text-foreground ${className}`}
      data-testid="knowledge-analysis-panel"
    >
      {/* Scrollable Container */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Header / Intro Banner */}
        <div className="rounded-lg border border-border/70 bg-card/40 p-3 space-y-1">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
            <BookOpen className="size-4 text-primary" />
            <span>Knowledge-Guided Analysis</span>
          </div>
          <p className="text-[11px] text-muted-foreground leading-relaxed">
            Apply user-defined engineering principles and architecture references to this repository or a specific file.
          </p>
        </div>

        {/* Loading Scopes */}
        {isLoadingScopes ? (
          <div className="flex items-center justify-center py-8 gap-2 text-xs text-muted-foreground">
            <Loader2 className="size-4 animate-spin text-primary" />
            <span>Loading knowledge scopes...</span>
          </div>
        ) : scopes.length === 0 ? (
          /* No Scopes Available */
          <div
            className="rounded-lg border border-dashed border-border p-4 text-center space-y-2 bg-muted/10"
            data-testid="no-knowledge-warning"
          >
            <BookOpen className="size-5 text-muted-foreground mx-auto" />
            <p className="text-xs font-medium text-foreground">No Engineering Knowledge Scopes</p>
            <p className="text-[11px] text-muted-foreground">
              You need to create an engineering knowledge scope and upload reference PDFs before running analysis.
            </p>
            <Link href="/knowledge">
              <Button size="sm" variant="outline" className="mt-2 text-xs h-7 gap-1.5 font-medium">
                <span>Manage Knowledge</span>
                <ExternalLink className="size-3" />
              </Button>
            </Link>
          </div>
        ) : (
          /* Analysis Form / State */
          <>
            {/* Scope Selection Form (collapsible or hidden once result is viewed) */}
            <div className="space-y-3.5 rounded-lg border border-border bg-card/30 p-3">
              {/* Engineering Knowledge Scope Dropdown */}
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <label
                    htmlFor="knowledge-scope-select"
                    className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider"
                  >
                    Engineering Knowledge
                  </label>
                  <Link
                    href="/knowledge"
                    className="text-[11px] text-primary hover:underline flex items-center gap-1"
                    title="Manage knowledge documents"
                  >
                    <span>Manage</span>
                    <ExternalLink className="size-2.5" />
                  </Link>
                </div>

                <select
                  id="knowledge-scope-select"
                  value={selectedKnowledgeId}
                  onChange={(e) => setSelectedKnowledgeId(e.target.value)}
                  disabled={isAnalyzing}
                  className="w-full rounded-md border border-input bg-background px-2.5 py-1.5 text-xs text-foreground outline-none focus:border-ring focus:ring-1 focus:ring-ring"
                  data-testid="knowledge-scope-select"
                >
                  {scopes.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name} ({s.documents?.length || 0} doc{s.documents?.length === 1 ? "" : "s"})
                    </option>
                  ))}
                </select>

                {selectedScope && completedDocsCount === 0 && (
                  <p className="text-[10px] text-destructive flex items-center gap-1 mt-1">
                    <AlertCircle className="size-3 shrink-0" />
                    <span>This scope has no indexed PDF documents. Upload documents in Knowledge.</span>
                  </p>
                )}
              </div>

              {/* Code Scope Selector */}
              <div className="space-y-1.5">
                <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">
                  Code Scope
                </label>
                <div className="flex rounded-md border border-input bg-muted/20 p-0.5 gap-1">
                  <button
                    type="button"
                    onClick={() => setCodeScopeType("repository")}
                    disabled={isAnalyzing}
                    className={`flex-1 flex items-center justify-center gap-1.5 py-1 px-2 rounded text-xs font-medium transition-colors cursor-pointer ${
                      codeScopeType === "repository"
                        ? "bg-card text-foreground shadow-xs border border-border/80"
                        : "text-muted-foreground hover:text-foreground"
                    }`}
                    data-testid="code-scope-repo"
                  >
                    <FolderGit2 className="size-3" />
                    <span>Whole Repository</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setCodeScopeType("file")}
                    disabled={isAnalyzing}
                    className={`flex-1 flex items-center justify-center gap-1.5 py-1 px-2 rounded text-xs font-medium transition-colors cursor-pointer ${
                      codeScopeType === "file"
                        ? "bg-card text-foreground shadow-xs border border-border/80"
                        : "text-muted-foreground hover:text-foreground"
                    }`}
                    data-testid="code-scope-file"
                  >
                    <FileCode2 className="size-3" />
                    <span>Specific File</span>
                  </button>
                </div>

                {/* File picker if codeScopeType === "file" */}
                {codeScopeType === "file" && (
                  <div className="mt-2 space-y-1" data-testid="file-scope-selector">
                    <select
                      value={selectedPath}
                      onChange={(e) => setSelectedPath(e.target.value)}
                      disabled={isAnalyzing}
                      className="w-full rounded-md border border-input bg-background px-2.5 py-1.5 text-xs text-foreground outline-none focus:border-ring focus:ring-1 focus:ring-ring font-mono"
                      data-testid="file-path-select"
                    >
                      {files.map((f) => (
                        <option key={f.path} value={f.path}>
                          {f.path}
                        </option>
                      ))}
                    </select>
                    {activeFilePath && selectedPath !== activeFilePath && (
                      <button
                        type="button"
                        onClick={() => setSelectedPath(activeFilePath)}
                        className="text-[10px] text-primary hover:underline cursor-pointer"
                      >
                        Use currently open file: {activeFilePath}
                      </button>
                    )}
                  </div>
                )}
              </div>

              {/* Question Textarea */}
              <div className="space-y-1.5">
                <label
                  htmlFor="analysis-question"
                  className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider"
                >
                  Question
                </label>
                <textarea
                  id="analysis-question"
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  disabled={isAnalyzing}
                  rows={3}
                  placeholder={
                    codeScopeType === "file"
                      ? "e.g. Based on the selected engineering knowledge, what pattern would you suggest for this file?"
                      : "e.g. Based on the selected knowledge, does this repository adhere to SOLID principles?"
                  }
                  className="w-full resize-none rounded-md border border-input bg-background px-3 py-2 text-xs text-foreground placeholder:text-muted-foreground/60 outline-none focus:border-ring focus:ring-1 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
                  data-testid="analysis-question-input"
                />
              </div>

              {/* Submit Button */}
              <div className="flex items-center justify-between pt-1">
                {result && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={handleReset}
                    className="h-7 text-xs gap-1 text-muted-foreground hover:text-foreground"
                    data-testid="reset-analysis-button"
                  >
                    <RotateCcw className="size-3" />
                    <span>Clear Result</span>
                  </Button>
                )}
                <Button
                  type="button"
                  size="sm"
                  onClick={() => handleRunAnalysis()}
                  disabled={
                    isAnalyzing ||
                    !question.trim() ||
                    !selectedKnowledgeId ||
                    completedDocsCount === 0 ||
                    (codeScopeType === "file" && !selectedPath)
                  }
                  className="h-7 px-3 text-xs gap-1.5 ml-auto font-medium"
                  data-testid="run-analysis-button"
                >
                  {isAnalyzing ? (
                    <>
                      <Loader2 className="size-3 animate-spin" />
                      <span>Analyzing...</span>
                    </>
                  ) : (
                    <>
                      <Send className="size-3" />
                      <span>Analyze</span>
                    </>
                  )}
                </Button>
              </div>
            </div>

            {/* Analysis In-Progress State */}
            {isAnalyzing && (
              <div
                className="rounded-lg border border-border/80 bg-muted/20 p-6 text-center space-y-2.5 animate-pulse"
                data-testid="analysis-loading"
              >
                <Loader2 className="size-6 animate-spin text-primary mx-auto" />
                <p className="text-xs font-medium text-foreground">
                  Synthesizing repository and engineering knowledge evidence...
                </p>
                <p className="text-[11px] text-muted-foreground max-w-xs mx-auto">
                  Retrieving relevant code chunks, engineering definitions, and formulating grounded reasoning.
                </p>
              </div>
            )}

            {/* Analysis Results Display */}
            {result && !isAnalyzing && (
              <div className="space-y-4 pt-1" data-testid="analysis-results">
                {/* Answer Card */}
                <div className="rounded-lg border border-border bg-card p-4 space-y-2.5 shadow-xs">
                  <div className="flex items-center justify-between border-b border-border/60 pb-2">
                    <span className="text-xs font-semibold text-foreground uppercase tracking-wider flex items-center gap-1.5">
                      <BookOpen className="size-3.5 text-primary" />
                      Analysis Answer
                    </span>
                    <Badge variant="outline" className="text-[10px] font-normal">
                      Grounded
                    </Badge>
                  </div>
                  <div className="text-xs leading-relaxed text-foreground prose-sm max-w-none" data-testid="analysis-answer">
                    <MarkdownRenderer content={result.answer} />
                  </div>
                </div>

                {/* Evidence: Visually Separated Domains */}
                <div className="space-y-3">
                  {/* Repository Evidence */}
                  <div className="rounded-lg border border-border bg-card/60 p-3 space-y-2" data-testid="repository-evidence-section">
                    <div className="flex items-center justify-between">
                      <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider flex items-center gap-1.5">
                        <FolderGit2 className="size-3 text-primary" />
                        Repository Evidence ({repoSources.length})
                      </span>
                    </div>

                    {repoSources.length === 0 ? (
                      <p className="text-[11px] text-muted-foreground italic px-1">
                        No repository evidence cited.
                      </p>
                    ) : (
                      <div className="space-y-1.5">
                        {repoSources.map((source, idx) => (
                          <div
                            key={`${source.source_id}-${idx}`}
                            className="flex items-center justify-between gap-2 rounded border border-border/60 bg-muted/20 px-2 py-1.5 text-xs transition-colors hover:border-primary/40"
                            data-testid={`repo-source-${idx}`}
                          >
                            <div className="min-w-0 flex-1 flex items-center gap-1.5 font-mono text-[11px]">
                              <FileCode2 className="size-3 shrink-0 text-muted-foreground" />
                              <span className="truncate text-foreground font-medium" title={source.path}>
                                {source.path}
                              </span>
                              {source.start_line !== null && source.start_line !== undefined && (
                                <span className="text-muted-foreground shrink-0">
                                  L{source.start_line}–{source.end_line}
                                </span>
                              )}
                            </div>
                            <button
                              type="button"
                              onClick={() => onSelectFile(source.path, source.start_line ?? undefined)}
                              className="shrink-0 flex items-center gap-1 text-[10px] font-medium text-muted-foreground hover:text-primary transition-colors cursor-pointer"
                              title={`Open ${source.path}`}
                              data-testid={`open-repo-source-${idx}`}
                            >
                              <span>Open</span>
                              <ArrowRight className="size-3" />
                            </button>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Engineering Knowledge Evidence */}
                  <div className="rounded-lg border border-border bg-card/60 p-3 space-y-2" data-testid="knowledge-evidence-section">
                    <div className="flex items-center justify-between">
                      <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider flex items-center gap-1.5">
                        <BookOpen className="size-3 text-primary" />
                        Engineering Knowledge Evidence ({knowledgeSources.length})
                      </span>
                    </div>

                    {knowledgeSources.length === 0 ? (
                      <p className="text-[11px] text-muted-foreground italic px-1">
                        No engineering knowledge evidence cited.
                      </p>
                    ) : (
                      <div className="space-y-1.5">
                        {knowledgeSources.map((source, idx) => (
                          <div
                            key={`${source.source_id}-${idx}`}
                            className="flex items-center justify-between gap-2 rounded border border-border/60 bg-muted/20 px-2 py-1.5 text-xs"
                            data-testid={`knowledge-source-${idx}`}
                          >
                            <div className="min-w-0 flex-1 flex items-center gap-1.5 font-mono text-[11px]">
                              <FileText className="size-3 shrink-0 text-primary/80" />
                              <span className="truncate text-foreground font-medium" title={source.path}>
                                {source.path}
                              </span>
                            </div>
                            {source.page_number !== null && source.page_number !== undefined && (
                              <Badge variant="outline" className="text-[10px] font-normal shrink-0">
                                Page {source.page_number}
                              </Badge>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
